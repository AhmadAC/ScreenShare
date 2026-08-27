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
    micMuted?: boolean;
    soundMuted?: boolean;
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
    toggleMic: () => void;
    toggleSystemAudio: () => void;
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

    // Audio management: Web Audio Mixer nodes
    const audioCtxRef = React.useRef<AudioContext | null>(null);
    const sysGainRef = React.useRef<GainNode | null>(null);
    const micGainRef = React.useRef<GainNode | null>(null);
    const micStreamRef = React.useRef<MediaStream | null>(null);
    const sysStreamRef = React.useRef<MediaStream | null>(null);
    const isMicMutedRef = React.useRef<boolean>(false);
    const isSoundMutedRef = React.useRef<boolean>(false);

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
                            setState({
                                ws,
                                ...event.payload,
                                clientStreams: [],
                                micMuted: isMicMutedRef.current,
                                soundMuted: isSoundMutedRef.current,
                            });
                            setRoomID(event.payload.id);
                        } else {
                            resolve();
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

                            // Deliver frozen video frame to new attendees if currently paused
                            const activeStream = new MediaStream();
                            stream.current.getAudioTracks().forEach((t) => activeStream.addTrack(t));

                            if (pauseDataRef.current.isPaused && pauseDataRef.current.frozenStream) {
                                const frozenVid = pauseDataRef.current.frozenStream.getVideoTracks()[0];
                                if (frozenVid) activeStream.addTrack(frozenVid);
                            } else {
                                const origVid = stream.current.getVideoTracks()[0];
                                if (origVid) activeStream.addTrack(origVid);
                            }

                            if (host.current[event.payload.id]) {
                                host.current[event.payload.id].close();
                                delete host.current[event.payload.id];
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
                            if (client.current[sid]) {
                                client.current[sid].close();
                                delete client.current[sid];
                            }
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
                                    setState((current) => {
                                        if (!current) return current;
                                        const deduplicated = current.clientStreams.filter(
                                            (s) => s.id !== sid && s.peer_id !== peer
                                        );
                                        return {
                                            ...current,
                                            clientStreams: [
                                                ...deduplicated,
                                                {
                                                    id: sid,
                                                    stream: inStream,
                                                    peer_id: peer,
                                                },
                                            ],
                                        };
                                    }),
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
                            delete client.current[event.payload];
                            delete host.current[event.payload];
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
        [setState, setRoomID]
    );

    const share = async () => {
        if (!navigator.mediaDevices || typeof navigator.mediaDevices.getDisplayMedia !== 'function') {
            enqueueSnackbar('Screensharing not supported in this browser.', {variant: 'error', persist: true});
            return;
        }

        try {
            // 1. Capture screen video and optional getDisplayMedia system audio
            let screenStream: MediaStream;
            try {
                screenStream = await navigator.mediaDevices.getDisplayMedia({
                    video: { frameRate: { ideal: 60, max: 60 } },
                    audio: {
                        echoCancellation: false,
                        noiseSuppression: false,
                        autoGainControl: false,
                    } as any,
                });
            } catch (err) {
                console.log('getDisplayMedia with audio failed, falling back to video only:', err);
                screenStream = await navigator.mediaDevices.getDisplayMedia({
                    video: { frameRate: { ideal: 60, max: 60 } },
                    audio: false,
                });
            }

            const combinedStream = new MediaStream();
            screenStream.getVideoTracks().forEach((track) => combinedStream.addTrack(track));

            // Set up Web Audio Context Mixer
            const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
            const audioCtx = new AudioContextClass();
            if (audioCtx.state === 'suspended') {
                audioCtx.resume().catch(() => {});
            }
            audioCtxRef.current = audioCtx;
            const audioDest = audioCtx.createMediaStreamDestination();

            const sysGain = audioCtx.createGain();
            sysGain.gain.setValueAtTime(isSoundMutedRef.current ? 0 : 1, audioCtx.currentTime);
            sysGain.connect(audioDest);
            sysGainRef.current = sysGain;

            const micGain = audioCtx.createGain();
            micGain.gain.setValueAtTime(isMicMutedRef.current ? 0 : 1, audioCtx.currentTime);
            micGain.connect(audioDest);
            micGainRef.current = micGain;

            // Enumerate audio input devices to distinguish system monitor/loopback devices from real physical microphones
            let audioDevices: MediaDeviceInfo[] = [];
            try {
                audioDevices = await navigator.mediaDevices.enumerateDevices();
                if (audioDevices.some((d) => d.kind === 'audioinput' && !d.label)) {
                    // Trigger permission probe so device labels become visible and inspectable
                    try {
                        const tempStream = await navigator.mediaDevices.getUserMedia({audio: true});
                        tempStream.getTracks().forEach((t) => t.stop());
                        audioDevices = await navigator.mediaDevices.enumerateDevices();
                    } catch (permErr) {
                        console.log('Permission probe skipped:', permErr);
                    }
                }
            } catch (enumErr) {
                console.log('Device enumeration failed:', enumErr);
            }

            const audioInputs = audioDevices.filter((d) => d.kind === 'audioinput');

            const isMonitorLabel = (label: string) => {
                const l = label.toLowerCase();
                return (
                    l.includes('computer sound') ||
                    l.includes('computersound') ||
                    l.includes('monitor of') ||
                    l.includes('.monitor') ||
                    l.includes('stereo mix') ||
                    l.includes('what u hear') ||
                    l.includes('wave out mix') ||
                    l.includes('loopback')
                );
            };

            // Connect system audio ONLY to the system audio gain bus
            const displayAudioTracks = screenStream.getAudioTracks();

            if (displayAudioTracks.length > 0) {
                sysStreamRef.current = new MediaStream(displayAudioTracks);
                const sysSource = audioCtx.createMediaStreamSource(sysStreamRef.current);
                sysSource.connect(sysGain);
            } else {
                // If getDisplayMedia provided no audio tracks, look specifically for a virtual/monitor device
                const monitorDevice = audioInputs.find((d) => isMonitorLabel(d.label));
                if (monitorDevice) {
                    try {
                        const fallbackAudio = await navigator.mediaDevices.getUserMedia({
                            audio: {
                                deviceId: { exact: monitorDevice.deviceId },
                                echoCancellation: false,
                                noiseSuppression: false,
                                autoGainControl: false,
                            } as any,
                        });
                        sysStreamRef.current = fallbackAudio;
                        const sysSource = audioCtx.createMediaStreamSource(fallbackAudio);
                        sysSource.connect(sysGain);
                    } catch (e) {
                        console.log('Could not open monitor audio device:', e);
                    }
                }
            }

            // Capture Real Physical Microphone (strictly avoiding monitor devices to prevent bleed into mic channel)
            const physicalMicDevice = audioInputs.find((d) => !isMonitorLabel(d.label) && d.deviceId);
            if (physicalMicDevice) {
                try {
                    const micStream = await navigator.mediaDevices.getUserMedia({
                        audio: {
                            deviceId: { exact: physicalMicDevice.deviceId },
                            echoCancellation: true,
                            noiseSuppression: true,
                            autoGainControl: true,
                        },
                    });
                    const micTracks = micStream.getAudioTracks();
                    if (micTracks.length > 0) {
                        if (isMicMutedRef.current) {
                            micTracks.forEach((t) => (t.enabled = false));
                        }
                        micStreamRef.current = micStream;
                        const micSource = audioCtx.createMediaStreamSource(micStream);
                        micSource.connect(micGain);
                    }
                } catch (micErr) {
                    console.log('Real physical microphone capture not available:', micErr);
                }
            }

            // Ensure initial track mute states match refs exactly
            if (sysStreamRef.current && isSoundMutedRef.current) {
                sysStreamRef.current.getAudioTracks().forEach((t) => (t.enabled = false));
            }
            if (micStreamRef.current && isMicMutedRef.current) {
                micStreamRef.current.getAudioTracks().forEach((t) => (t.enabled = false));
            }

            // Attach the mixed audio track to the outgoing stream
            const mixedAudioTracks = audioDest.stream.getAudioTracks();
            if (mixedAudioTracks.length > 0) {
                combinedStream.addTrack(mixedAudioTracks[0]);
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
        setState((current) => (current ? {
            ...current,
            hostStream: stream.current,
            paused: false,
            micMuted: isMicMutedRef.current,
            soundMuted: isSoundMutedRef.current,
        } : current));

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

        micStreamRef.current?.getTracks().forEach((t) => t.stop());
        micStreamRef.current = null;
        if (sysStreamRef.current && sysStreamRef.current !== stream.current) {
            sysStreamRef.current.getTracks().forEach((t) => t.stop());
        }
        sysStreamRef.current = null;

        if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
            audioCtxRef.current.close().catch(() => {});
        }
        audioCtxRef.current = null;

        Object.values(host.current).forEach((peer) => {
            peer.close();
        });
        host.current = {};
        stream.current?.getTracks().forEach((track) => track.stop());
        stream.current = undefined;
        conn.current?.send(JSON.stringify({type: 'stopshare', payload: {}}));
        setState((current) => (current ? {
            ...current,
            hostStream: undefined,
            paused: false,
            micMuted: isMicMutedRef.current,
            soundMuted: isSoundMutedRef.current,
        } : current));
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
            document.body.appendChild(video);
            video.srcObject = stream.current;
            video.muted = true;
            video.playsInline = true;

            try {
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
                video.remove();

                const getStream = (canvas as any).captureStream || (canvas as any).mozCaptureStream;
                if (!getStream) throw new Error('captureStream not supported in this browser');

                const frozenStream = getStream.call(canvas, 5);
                const frozenVideoTrack = frozenStream.getVideoTracks()[0];

                pauseDataRef.current.frozenStream = frozenStream;

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
                console.error('Failed to freeze frame, falling back to blank frame:', e);
                stream.current.getVideoTracks()[0].enabled = false;
            }
        }
    };

    const toggleMic = () => {
        isMicMutedRef.current = !isMicMutedRef.current;
        const isMuted = isMicMutedRef.current;
        if (micGainRef.current && audioCtxRef.current) {
            micGainRef.current.gain.setValueAtTime(
                isMuted ? 0 : 1,
                audioCtxRef.current.currentTime
            );
        } else if (micGainRef.current) {
            micGainRef.current.gain.value = isMuted ? 0 : 1;
        }
        if (micStreamRef.current) {
            micStreamRef.current.getAudioTracks().forEach((track) => {
                track.enabled = !isMuted;
            });
        }
        setState((current) => (current ? {...current, micMuted: isMuted} : current));
    };

    const toggleSystemAudio = () => {
        isSoundMutedRef.current = !isSoundMutedRef.current;
        const isMuted = isSoundMutedRef.current;
        if (sysGainRef.current && audioCtxRef.current) {
            sysGainRef.current.gain.setValueAtTime(
                isMuted ? 0 : 1,
                audioCtxRef.current.currentTime
            );
        } else if (sysGainRef.current) {
            sysGainRef.current.gain.value = isMuted ? 0 : 1;
        }
        if (sysStreamRef.current) {
            sysStreamRef.current.getAudioTracks().forEach((track) => {
                track.enabled = !isMuted;
            });
        }
        setState((current) => (current ? {...current, soundMuted: isMuted} : current));
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

    return {state, room, share, stopShare, setName, togglePause, toggleMic, toggleSystemAudio};
};