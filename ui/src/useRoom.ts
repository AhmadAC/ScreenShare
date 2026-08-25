// server/ui/src/useRoom.ts
import {useSnackbar} from 'notistack';
import React from 'react';

import {
    ICEServer,
    IncomingMessage,
    JoinRoom,
    OutgoingMessage,
    RoomCreate,
    RoomInfo,
    UIConfig,
} from './message';
import {loadSettings, resolveCodecPlaceholder} from './settings';
import {urlWithSlash} from './url';
import {authModeToRoomMode} from './useConfig';
import {getFromURL, useRoomID} from './useRoomID';

export type RoomState = false | ConnectedRoom;
export type ConnectedRoom = {
    ws: WebSocket;
    hostStream?: MediaStream;
    clientStreams: ClientStream[];
    paused?: boolean;
} & RoomInfo;

interface ClientStream {
    id: string;
    peer_id: string;
    stream: MediaStream;
}

export interface UseRoom {
    state: RoomState;
    room: FCreateRoom;
    share: () => void;
    setName: (name: string) => void;
    stopShare: () => void;
    togglePause: () => void;
}

const relayConfig: Partial<RTCConfiguration> =
    window.location.search.indexOf('forceTurn=true') !== -1 ? {iceTransportPolicy: 'relay'} : {};

const hostSession = async ({
    sid,
    ice,
    send,
    done,
    stream,
}: {
    sid: string;
    ice: ICEServer[];
    send: (e: OutgoingMessage) => void;
    done: () => void;
    stream: MediaStream;
}): Promise<RTCPeerConnection> => {
    const peer = new RTCPeerConnection({...relayConfig, iceServers: ice});
    peer.onicecandidate = (event) => {
        if (!event.candidate) {
            return;
        }
        send({type: 'hostice', payload: {sid: sid, value: event.candidate}});
    };

    peer.onconnectionstatechange = (event) => {
        console.log('host change', event);
        if (
            peer.connectionState === 'closed' ||
            peer.connectionState === 'disconnected' ||
            peer.connectionState === 'failed'
        ) {
            peer.close();
            done();
        }
    };

    stream.getTracks().forEach((track) => peer.addTrack(track, stream));

    const preferCodec = resolveCodecPlaceholder(loadSettings().preferCodec);
    if (preferCodec) {
        const transceiver = peer
            .getTransceivers()
            .find((t) => t.sender && t.sender.track === stream.getVideoTracks()[0]);

        if (!!transceiver && 'setCodecPreferences' in transceiver) {
            const exactMatch: RTCRtpCodec[] = [];
            const mimeMatch: RTCRtpCodec[] = [];
            const others: RTCRtpCodec[] = [];

            RTCRtpReceiver.getCapabilities('video')?.codecs.forEach((codec) => {
                if (codec.mimeType === preferCodec.mimeType) {
                    if (codec.sdpFmtpLine === preferCodec.sdpFmtpLine) {
                        exactMatch.push(codec);
                    } else {
                        mimeMatch.push(codec);
                    }
                } else {
                    others.push(codec);
                }
            });

            const sortedCodecs = [...exactMatch, ...mimeMatch, ...others];

            console.log('Setting codec preferences', sortedCodecs);
            transceiver.setCodecPreferences(sortedCodecs);
        }
    }

    const hostOffer = await peer.createOffer({offerToReceiveVideo: true});
    await peer.setLocalDescription(hostOffer);
    send({type: 'hostoffer', payload: {value: hostOffer, sid: sid}});

    return peer;
};

const clientSession = async ({
    sid,
    ice,
    send,
    done,
    onTrack,
}: {
    sid: string;
    ice: ICEServer[];
    send: (e: OutgoingMessage) => void;
    onTrack: (s: MediaStream) => void;
    done: () => void;
}): Promise<RTCPeerConnection> => {
    console.log('ice', ice);
    const peer = new RTCPeerConnection({...relayConfig, iceServers: ice});
    peer.onicecandidate = (event) => {
        if (!event.candidate) {
            return;
        }
        send({type: 'clientice', payload: {sid: sid, value: event.candidate}});
    };
    peer.onconnectionstatechange = (event) => {
        console.log('client change', event);
        if (
            peer.connectionState === 'closed' ||
            peer.connectionState === 'disconnected' ||
            peer.connectionState === 'failed'
        ) {
            peer.close();
            done();
        }
    };

    let notified = false;
    const stream = new MediaStream();
    peer.ontrack = (event) => {
        stream.addTrack(event.track);
        if (!notified) {
            notified = true;
            onTrack(stream);
        }
    };

    return peer;
};

export type FCreateRoom = (room: RoomCreate | JoinRoom) => Promise<void>;

export const useRoom = (config: UIConfig): UseRoom => {
    const [roomID, setRoomID] = useRoomID();
    const {enqueueSnackbar} = useSnackbar();
    const conn = React.useRef<WebSocket | undefined>(undefined);
    const host = React.useRef<Record<string, RTCPeerConnection>>({});
    const client = React.useRef<Record<string, RTCPeerConnection>>({});
    const stream = React.useRef<MediaStream>(undefined);
    const pauseDataRef = React.useRef<{
        isPaused?: boolean;
        intervalId?: number;
        frozenStream?: MediaStream;
    }>({});

    const [state, setState] = React.useState<RoomState>(false);

    const room: FCreateRoom = React.useCallback(
        (create) => {
            return new Promise<void>((resolve) => {
                const ws = (conn.current = new WebSocket(
                    urlWithSlash.replace('http', 'ws') + 'stream'
                ));
                const send = (message: OutgoingMessage) => {
                    if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(message));
                };
                let first = true;
                ws.onmessage = (data) => {
                    const event: IncomingMessage = JSON.parse(data.data);
                    if (first) {
                        first = false;
                        if (event.type === 'room') {
                            resolve();
                            setState({ws, ...event.payload, clientStreams: []});
                            setRoomID(event.payload.id);
                        } else {
                            resolve();
                            enqueueSnackbar('Unknown Event: ' + event.type, {variant: 'error'});
                            ws.close(1000, 'received unknown event');
                        }
                        return;
                    }

                    switch (event.type) {
                        case 'room':
                            setState((current) =>
                                current ? {...current, ...event.payload} : current
                            );
                            return;
                        case 'hostsession':
                            if (!stream.current) {
                                return;
                            }

                            // Deliver frozen video framework to new attendees if paused
                            const activeStream = new MediaStream();
                            stream.current.getAudioTracks().forEach((t) => activeStream.addTrack(t));
                            
                            if (pauseDataRef.current.isPaused && pauseDataRef.current.frozenStream) {
                                const frozenVid = pauseDataRef.current.frozenStream.getVideoTracks()[0];
                                if (frozenVid) activeStream.addTrack(frozenVid);
                            } else {
                                const origVid = stream.current.getVideoTracks()[0];
                                if (origVid) activeStream.addTrack(origVid);
                            }

                            hostSession({
                                sid: event.payload.id,
                                stream: activeStream,
                                ice: event.payload.iceServers,
                                send,
                                done: () => delete host.current[event.payload.id],
                            }).then((peer) => {
                                host.current[event.payload.id] = peer;
                            });
                            return;
                        case 'clientsession':
                            const {id: sid, peer} = event.payload;
                            clientSession({
                                sid,
                                send,
                                ice: event.payload.iceServers,
                                done: () => {
                                    delete client.current[sid];
                                    setState((current) =>
                                        current
                                            ? {
                                                  ...current,
                                                  clientStreams: current.clientStreams.filter(
                                                      ({id}) => id !== sid
                                                  ),
                                              }
                                            : current
                                    );
                                },
                                onTrack: (inStream) =>
                                    setState((current) =>
                                        current
                                            ? {
                                                  ...current,
                                                  clientStreams: [
                                                      ...current.clientStreams,
                                                      {
                                                          id: sid,
                                                          stream: inStream,
                                                          peer_id: peer,
                                                      },
                                                  ],
                                              }
                                            : current
                                    ),
                            }).then((newPeer) => (client.current[event.payload.id] = newPeer));
                            return;
                        case 'clientice':
                            host.current[event.payload.sid]?.addIceCandidate(event.payload.value);
                            return;
                        case 'clientanswer':
                            host.current[event.payload.sid]?.setRemoteDescription(
                                event.payload.value
                            );
                            return;
                        case 'hostoffer':
                            (async () => {
                                await client.current[event.payload.sid]?.setRemoteDescription(
                                    event.payload.value
                                );
                                const answer =
                                    await client.current[event.payload.sid]?.createAnswer();
                                await client.current[event.payload.sid]?.setLocalDescription(
                                    answer
                                );
                                send({
                                    type: 'clientanswer',
                                    payload: {sid: event.payload.sid, value: answer},
                                });
                            })();
                            return;
                        case 'hostice':
                            client.current[event.payload.sid]?.addIceCandidate(event.payload.value);
                            return;
                        case 'endshare':
                            client.current[event.payload]?.close();
                            host.current[event.payload]?.close();
                            setState((current) =>
                                current
                                    ? {
                                          ...current,
                                          clientStreams: current.clientStreams.filter(
                                              ({id}) => id !== event.payload
                                          ),
                                      }
                                    : current
                            );
                    }
                };
                ws.onclose = () => {
                    if (first) {
                        resolve();
                        first = false;
                    }
                    setState(false);
                };
                ws.onerror = () => {
                    if (first) {
                        resolve();
                        first = false;
                    }
                    setState(false);
                };
                ws.onopen = () => {
                    create.payload.username = loadSettings().name;
                    send(create);
                };
            });
        },
        [setState, enqueueSnackbar, setRoomID]
    );

    const share = async () => {
        if (!navigator.mediaDevices || typeof navigator.mediaDevices.getDisplayMedia !== 'function') {
            enqueueSnackbar('Screensharing not supported in this browser.', {variant: 'error', persist: true});
            return;
        }

        try {
            // 1. Capture screen video. We MUST request audio here to prevent Edge fake-ui crash
            let screenStream: MediaStream;
            try {
                screenStream = await navigator.mediaDevices.getDisplayMedia({
                    video: { frameRate: { ideal: 60, max: 60 } },
                    audio: true, 
                });
            } catch (err) {
                console.log('getDisplayMedia failed:', err);
                screenStream = await navigator.mediaDevices.getDisplayMedia({
                    video: { frameRate: { ideal: 60, max: 60 } },
                    audio: false,
                });
            }

            const combinedStream = new MediaStream();

            // Add ONLY the video track to our combined stream
            screenStream.getVideoTracks().forEach((track) => combinedStream.addTrack(track));

            // Instantly stop the fake "beep" audio track generated by Edge to prevent noise
            screenStream.getAudioTracks().forEach((track) => track.stop());

            // 2. Capture real system audio via getUserMedia with all processing disabled
            // Disabling processing prevents Edge WebRTC Acoustic Echo Cancellation from crashing
            try {
                let audioStream: MediaStream | null = null;
                try {
                    audioStream = await navigator.mediaDevices.getUserMedia({
                        audio: {
                            echoCancellation: false,
                            noiseSuppression: false,
                            autoGainControl: false,
                            googEchoCancellation: false,
                            googAutoGainControl: false,
                            googNoiseSuppression: false,
                            googHighpassFilter: false,
                        } as any
                    });
                } catch (strictErr) {
                    console.log('Strict audio constraints failed, trying basic audio:', strictErr);
                    try {
                        audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    } catch(fallbackErr) {
                        console.log('Basic audio failed. Attempting to force any available microphone device.', fallbackErr);
                        const devices = await navigator.mediaDevices.enumerateDevices();
                        const audioInputs = devices.filter(d => d.kind === 'audioinput');
                        if (audioInputs.length > 0) {
                            audioStream = await navigator.mediaDevices.getUserMedia({
                                audio: { deviceId: { exact: audioInputs[0].deviceId }, echoCancellation: false }
                            });
                        } else {
                            throw new Error('No audio input devices found by browser.');
                        }
                    }
                }
                
                if (audioStream) {
                    audioStream.getAudioTracks().forEach((track) => combinedStream.addTrack(track));
                }
            } catch (audioErr: any) {
                console.log('Could not capture audio stream via getUserMedia:', audioErr);
                enqueueSnackbar(`Sharing video only (Audio capture unavailable: ${audioErr.message || audioErr})`, {
                    variant: 'warning',
                });
            }

            stream.current = combinedStream;
        } catch (e: any) {
            enqueueSnackbar(`Could not start presentation: ${e.message || e.name || e}`, {
                variant: 'error',
                persist: true,
            });
            return;
        }

        stream.current?.getVideoTracks()[0].addEventListener('ended', () => stopShare());
        setState((current) => (current ? {...current, hostStream: stream.current, paused: false} : current));

        conn.current?.send(JSON.stringify({type: 'share', payload: {}}));
    };

    const stopShare = async () => {
        if (pauseDataRef.current.intervalId) {
            window.clearInterval(pauseDataRef.current.intervalId);
        }
        pauseDataRef.current.frozenStream?.getTracks().forEach((t) => {
            if (t.kind === 'video') t.stop();
        });
        pauseDataRef.current = {};

        Object.values(host.current).forEach((peer) => {
            peer.close();
        });
        host.current = {};
        stream.current?.getTracks().forEach((track) => track.stop());
        stream.current = undefined;
        conn.current?.send(JSON.stringify({type: 'stopshare', payload: {}}));
        setState((current) => (current ? {...current, hostStream: undefined, paused: false} : current));
    };

    const togglePause = async () => {
        if (!stream.current || stream.current.getVideoTracks().length === 0) return;
        
        const isCurrentlyPaused = pauseDataRef.current.isPaused || false;
        
        if (isCurrentlyPaused) {
            if (pauseDataRef.current.intervalId) {
                window.clearInterval(pauseDataRef.current.intervalId);
                pauseDataRef.current.intervalId = undefined;
            }
            pauseDataRef.current.frozenStream?.getTracks().forEach((t) => {
                if (t.kind === 'video') t.stop();
            });
            pauseDataRef.current.frozenStream = undefined;
            pauseDataRef.current.isPaused = false;
            
            const originalVideoTrack = stream.current.getVideoTracks()[0];
            originalVideoTrack.enabled = true;
            
            Object.values(host.current).forEach((peer) => {
                const sender = peer.getSenders().find((s) => s.track?.kind === 'video');
                if (sender) {
                    sender.replaceTrack(originalVideoTrack).catch(console.error);
                }
            });
            
            setState((current) => (current ? {...current, paused: false} : current));
        } else {
            pauseDataRef.current.isPaused = true;
            setState((current) => (current ? {...current, paused: true} : current));
            
            const video = document.createElement('video');
            video.style.display = 'none';
            document.body.appendChild(video); // Force render in active DOM so Chromium decodes frames
            video.srcObject = stream.current;
            video.muted = true;
            video.playsInline = true;
            
            try {
                // Wait for the video feed first frame data to actually be available
                await new Promise<void>((resolve, reject) => {
                    video.onloadeddata = () => {
                        video.play().then(resolve).catch(reject);
                    };
                    window.setTimeout(() => reject(new Error('Timeout loading video metadata')), 1500);
                });
                
                const canvas = document.createElement('canvas');
                canvas.width = video.videoWidth || 1920;
                canvas.height = video.videoHeight || 1080;
                const ctx = canvas.getContext('2d');
                if (ctx) {
                    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                }
                
                video.pause();
                video.srcObject = null;
                video.remove(); // Cleanly remove the hidden video from the DOM
                
                const getStream = (canvas as any).captureStream || (canvas as any).mozCaptureStream;
                if (!getStream) throw new Error('captureStream not supported in this browser');
                
                // Set fps to 5 keeping the connection alive whilst drastically lowering bandwidth
                const frozenStream = getStream.call(canvas, 5);
                const frozenVideoTrack = frozenStream.getVideoTracks()[0];
                
                pauseDataRef.current.frozenStream = frozenStream;
                
                // Periodic ping on the canvas. Keeps the stream active without black screening on obscure browsers
                const staticImg = ctx?.getImageData(0, 0, canvas.width, canvas.height);
                pauseDataRef.current.intervalId = window.setInterval(() => {
                    if (staticImg && ctx) ctx.putImageData(staticImg, 0, 0);
                }, 500);

                Object.values(host.current).forEach((peer) => {
                    const sender = peer.getSenders().find((s) => s.track?.kind === 'video');
                    if (sender) {
                        sender.replaceTrack(frozenVideoTrack).catch(console.error);
                    }
                });
            } catch (e) {
                console.error('Failed to freeze frame, falling back to black frame:', e);
                stream.current.getVideoTracks()[0].enabled = false;
            }
        }
    };

    const setName = (name: string): void => {
        conn.current?.send(JSON.stringify({type: 'name', payload: {username: name}}));
    };

    React.useEffect(() => {
        if (roomID) {
            const create = getFromURL('create') === 'true';
            if (create) {
                const closeOnOwnerLeaveString = getFromURL('closeOnOwnerLeave');
                const closeOnOwnerLeave =
                    closeOnOwnerLeaveString === undefined
                        ? config.closeRoomWhenOwnerLeaves
                        : closeOnOwnerLeaveString === 'true';
                room({
                    type: 'create',
                    payload: {
                        joinIfExist: true,
                        closeOnOwnerLeave,
                        id: roomID,
                        mode: authModeToRoomMode(config.authMode, config.loggedIn),
                    },
                });
            } else {
                room({type: 'join', payload: {id: roomID}});
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return {state, room, share, stopShare, setName, togglePause};
};