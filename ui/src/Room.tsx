// server/ui/src/Room.tsx
import React, {useCallback} from 'react';
import {Badge, Box, IconButton, Paper, Tooltip, Typography, Slider, Stack} from '@mui/material';
import CancelPresentationIcon from '@mui/icons-material/CancelPresentation';
import PresentToAllIcon from '@mui/icons-material/PresentToAll';
import FullScreenIcon from '@mui/icons-material/Fullscreen';
import PeopleIcon from '@mui/icons-material/People';
import VolumeMuteIcon from '@mui/icons-material/VolumeOff';
import VolumeIcon from '@mui/icons-material/VolumeUp';
import SettingsIcon from '@mui/icons-material/Settings';
import PausePresentationIcon from '@mui/icons-material/PausePresentation';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import {useHotkeys} from 'react-hotkeys-hook';
import {Video} from './Video';
import {makeStyles} from 'tss-react/mui';
import {ConnectedRoom} from './useRoom';
import {useSnackbar} from 'notistack';
import {RoomUser} from './message';
import {useSettings, VideoDisplayMode} from './settings';
import {SettingDialog} from './SettingDialog';

const HostStream: unique symbol = Symbol('mystream');

const flags = (user: RoomUser) => {
    const result: string[] = [];
    if (user.you) {
        result.push('You');
    }
    if (user.owner) {
        result.push('Owner');
    }
    if (user.streaming) {
        result.push('Streaming');
    }
    if (!result.length) {
        return '';
    }
    return ` (${result.join(', ')})`;
};

interface FullScreenHTMLVideoElement extends HTMLVideoElement {
    msRequestFullscreen?: () => void;
    mozRequestFullScreen?: () => void;
    webkitRequestFullscreen?: () => void;
}

const requestFullscreen = (element: FullScreenHTMLVideoElement | null) => {
    if (element?.requestFullscreen) {
        element.requestFullscreen();
    } else if (element?.mozRequestFullScreen) {
        element.mozRequestFullScreen();
    } else if (element?.msRequestFullscreen) {
        element.msRequestFullscreen();
    } else if (element?.webkitRequestFullscreen) {
        element.webkitRequestFullscreen();
    }
};

export const Room = ({
    state,
    share,
    stopShare,
    setName,
    togglePause,
}: {
    state: ConnectedRoom;
    share: () => void;
    stopShare: () => void;
    setName: (name: string) => void;
    togglePause: () => void;
}) => {
    const {classes} = useStyles();
    const [open, setOpen] = React.useState(false);
    const {enqueueSnackbar} = useSnackbar();
    const [settings, setSettings] = useSettings();
    const [showControl, setShowControl] = React.useState(true);
    const [hoverControl, setHoverControl] = React.useState(false);
    const [selectedStream, setSelectedStream] = React.useState<string | typeof HostStream>();
    const [videoElement, setVideoElement] = React.useState<FullScreenHTMLVideoElement | null>(null);
    const [audioBlocked, setAudioBlocked] = React.useState(false);

    useShowOnMouseMovement(setShowControl);

    const handleFullscreen = useCallback(() => requestFullscreen(videoElement), [videoElement]);

    React.useEffect(() => {
        if (selectedStream === HostStream && state.hostStream) {
            return;
        }
        if (state.clientStreams.some(({id}) => id === selectedStream)) {
            return;
        }
        if (state.clientStreams.length === 0 && selectedStream) {
            setSelectedStream(undefined);
            return;
        }
        setSelectedStream(state.clientStreams[0]?.id);
    }, [state.clientStreams, selectedStream, state.hostStream]);

    const stream =
        selectedStream === HostStream
            ? state.hostStream
            : state.clientStreams.find(({id}) => selectedStream === id)?.stream;

    const isHostSelfStream = selectedStream === HostStream || (!!state.hostStream && stream === state.hostStream);

    React.useEffect(() => {
        if (videoElement && stream && !isHostSelfStream) {
            videoElement.srcObject = stream;
            videoElement.muted = false;
            videoElement
                .play()
                .then(() => setAudioBlocked(false))
                .catch((err) => {
                    console.log('Could not play main video', err);
                    if (err.name === 'NotAllowedError') {
                        videoElement.muted = true;
                        videoElement
                            .play()
                            .then(() => {
                                if ((stream.getAudioTracks().length ?? 0) > 0) {
                                    setAudioBlocked(true);
                                }
                            })
                            .catch((retryErr) =>
                                console.log('Could not play main video with mute', retryErr)
                            );
                    }
                });
        }
    }, [videoElement, stream, isHostSelfStream]);

    const enableAudio = () => {
        if (videoElement) {
            videoElement.muted = false;
            videoElement
                .play()
                .then(() => setAudioBlocked(false))
                .catch((err) => console.log('Failed to unmute video', err));
        }
    };

    const copyLink = () => {
        navigator?.clipboard?.writeText(window.location.href)?.then(
            () => enqueueSnackbar('Link Copied', {variant: 'success'}),
            (err) => enqueueSnackbar('Copy Failed ' + err, {variant: 'error'})
        );
    };

    const setHoverState = React.useMemo(
        () => ({
            onMouseLeave: () => setHoverControl(false),
            onMouseEnter: () => setHoverControl(true),
        }),
        [setHoverControl]
    );

    const controlVisible = showControl || open || hoverControl;

    useHotkeys('s', () => (state.hostStream ? stopShare() : share()), [state.hostStream]);
    useHotkeys(
        'p',
        () => {
            if (state.hostStream) {
                togglePause();
            }
        },
        [state.hostStream]
    );
    useHotkeys(
        'f',
        () => {
            if (selectedStream) {
                handleFullscreen();
            }
        },
        [handleFullscreen, selectedStream]
    );
    useHotkeys('c', copyLink);
    useHotkeys(
        'h',
        () => {
            if (state.clientStreams !== undefined && state.clientStreams.length > 0) {
                const currentStreamIndex = state.clientStreams.findIndex(
                    ({id}) => id === selectedStream
                );
                const nextIndex =
                    currentStreamIndex === state.clientStreams.length - 1
                        ? 0
                        : currentStreamIndex + 1;
                setSelectedStream(state.clientStreams[nextIndex].id);
            }
        },
        [state.clientStreams, selectedStream]
    );
    useHotkeys(
        'l',
        () => {
            if (state.clientStreams !== undefined && state.clientStreams.length > 0) {
                const currentStreamIndex = state.clientStreams.findIndex(
                    ({id}) => id === selectedStream
                );
                const previousIndex =
                    currentStreamIndex === 0
                        ? state.clientStreams.length - 1
                        : currentStreamIndex - 1;
                setSelectedStream(state.clientStreams[previousIndex].id);
            }
        },
        [state.clientStreams, selectedStream]
    );
    useHotkeys(
        'm',
        () => {
            if (videoElement) {
                videoElement.muted = !videoElement.muted;
                if (!videoElement.muted) {
                    setAudioBlocked(false);
                }
            }
        },
        [videoElement]
    );

    // Polling background loop for OS Global Hotkey and PySide6 GUI
    React.useEffect(() => {
        const interval = setInterval(() => {
            fetch('http://127.0.0.1:5055/poll')
                .then((res) => res.json())
                .then((data) => {
                    if (data.action === 'toggle_pause') {
                        togglePause();
                    } else if (data.action === 'start_share') {
                        if (!state.hostStream) share();
                    } else if (data.action === 'stop_share') {
                        if (state.hostStream) stopShare();
                    }
                })
                .catch(() => {}); // Fails silently if python helper is not running
        }, 300);

        return () => clearInterval(interval);
    }, [state.hostStream, togglePause, share, stopShare]);

    // Post active streaming state back to PySide6 GUI for synchronization
    React.useEffect(() => {
        fetch('http://127.0.0.1:5055/state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sharing: !!state.hostStream,
                paused: !!state.paused
            })
        }).catch(() => {});
    }, [state.hostStream, state.paused]);

    const videoClasses = () => {
        switch (settings.displayMode) {
            case VideoDisplayMode.FitToWindow:
                return `${classes.video} ${classes.videoWindowFit}`;
            case VideoDisplayMode.OriginalSize:
                return `${classes.video}`;
            case VideoDisplayMode.FitWidth:
                return `${classes.video} ${classes.videoWindowWidth}`;
            case VideoDisplayMode.FitHeight:
                return `${classes.video} ${classes.videoWindowHeight}`;
        }
    };

    return (
        <div className={classes.videoContainer}>
            {controlVisible && (
                <Paper className={classes.title} elevation={10} {...setHoverState}>
                    <Tooltip title="Copy Link">
                        <Typography
                            variant="h4"
                            component="h4"
                            style={{cursor: 'pointer'}}
                            onClick={copyLink}
                        >
                            {state.id}
                        </Typography>
                    </Tooltip>
                </Paper>
            )}

            {audioBlocked && !isHostSelfStream && (
                <Paper
                    elevation={10}
                    style={{
                        position: 'fixed',
                        top: '90px',
                        left: '50%',
                        transform: 'translateX(-50%)',
                        zIndex: 40,
                        backgroundColor: '#fabd2f',
                        color: '#282828',
                        padding: '10px 20px',
                        cursor: 'pointer',
                        borderRadius: '8px',
                        fontWeight: 'bold',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '10px',
                    }}
                    onClick={enableAudio}
                >
                    <VolumeIcon />
                    <Typography variant="body1" style={{fontWeight: 'bold', color: '#282828'}}>
                        Tap here to enable sound
                    </Typography>
                </Paper>
            )}

            {stream && !isHostSelfStream ? (
                <video
                    ref={setVideoElement}
                    className={videoClasses()}
                    onDoubleClick={handleFullscreen}
                    playsInline
                />
            ) : isHostSelfStream ? (
                <Typography
                    variant="h4"
                    align="center"
                    component="div"
                    style={{
                        top: '50%',
                        left: '50%',
                        position: 'absolute',
                        transform: 'translate(-50%, -50%)',
                    }}
                >
                    You are sharing your screen
                </Typography>
            ) : (
                <Typography
                    variant="h4"
                    align="center"
                    component="div"
                    style={{
                        top: '50%',
                        left: '50%',
                        position: 'absolute',
                        transform: 'translate(-50%, -50%)',
                    }}
                >
                    no stream available
                </Typography>
            )}

            {controlVisible && (
                <Paper className={classes.control} elevation={10} {...setHoverState}>
                    {(stream?.getAudioTracks().length ?? 0) > 0 && videoElement && !isHostSelfStream && (
                        <AudioControl video={videoElement} onUnmute={() => setAudioBlocked(false)} />
                    )}
                    <Box sx={{whiteSpace: 'nowrap'}}>
                        {state.hostStream ? (
                            <>
                                <Tooltip title={state.paused ? "Resume Presentation" : "Pause Presentation"} arrow>
                                    <IconButton onClick={togglePause} size="large">
                                        {state.paused ? (
                                            <PlayArrowIcon fontSize="large" />
                                        ) : (
                                            <PausePresentationIcon fontSize="large" />
                                        )}
                                    </IconButton>
                                </Tooltip>
                                <Tooltip title="Cancel Presentation" arrow>
                                    <IconButton onClick={stopShare} size="large">
                                        <CancelPresentationIcon fontSize="large" />
                                    </IconButton>
                                </Tooltip>
                            </>
                        ) : (
                            <Tooltip title="Start Presentation" arrow>
                                <IconButton onClick={share} size="large">
                                    <PresentToAllIcon fontSize="large" />
                                </IconButton>
                            </Tooltip>
                        )}

                        <Tooltip
                            classes={{tooltip: classes.noMaxWidth}}
                            title={
                                <div>
                                    <Typography variant="h5">Member List</Typography>
                                    {state.users.map((user) => (
                                        <Typography key={user.id}>
                                            {user.name} {flags(user)}
                                        </Typography>
                                    ))}
                                </div>
                            }
                            arrow
                        >
                            <Badge badgeContent={state.users.length} color="primary">
                                <PeopleIcon fontSize="large" />
                            </Badge>
                        </Tooltip>
                        <Tooltip title="Fullscreen" arrow>
                            <IconButton
                                onClick={() => handleFullscreen()}
                                disabled={!selectedStream || isHostSelfStream}
                                size="large"
                            >
                                <FullScreenIcon fontSize="large" />
                            </IconButton>
                        </Tooltip>

                        <Tooltip title="Settings" arrow>
                            <IconButton onClick={() => setOpen(true)} size="large">
                                <SettingsIcon fontSize="large" />
                            </IconButton>
                        </Tooltip>
                    </Box>
                </Paper>
            )}

            <div className={classes.bottomContainer}>
                {state.clientStreams
                    .filter(({id}) => id !== selectedStream)
                    .map((client) => {
                        return (
                            <Paper
                                key={client.id}
                                elevation={4}
                                className={classes.smallVideoContainer}
                                onClick={() => setSelectedStream(client.id)}
                            >
                                <Video
                                    key={client.id}
                                    src={client.stream}
                                    className={classes.smallVideo}
                                />
                                <Typography
                                    variant="subtitle1"
                                    component="div"
                                    align="center"
                                    className={classes.smallVideoLabel}
                                >
                                    {state.users.find(({id}) => client.peer_id === id)?.name ??
                                        'unknown'}
                                </Typography>
                            </Paper>
                        );
                    })}
                <SettingDialog
                    open={open}
                    setOpen={setOpen}
                    updateName={setName}
                    saveSettings={setSettings}
                />
            </div>
        </div>
    );
};

const useShowOnMouseMovement = (doShow: (s: boolean) => void) => {
    const timeoutHandle = React.useRef(0);

    React.useEffect(() => {
        const update = () => {
            if (timeoutHandle.current === 0) {
                doShow(true);
            }

            clearTimeout(timeoutHandle.current);
            timeoutHandle.current = window.setTimeout(() => {
                timeoutHandle.current = 0;
                doShow(false);
            }, 1000);
        };
        window.addEventListener('mousemove', update);
        return () => window.removeEventListener('mousemove', update);
    }, [doShow]);

    React.useEffect(
        () =>
            void (timeoutHandle.current = window.setTimeout(() => {
                timeoutHandle.current = 0;
                doShow(false);
            }, 1000)),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        []
    );
};

const AudioControl = ({
    video,
    onUnmute,
}: {
    video: FullScreenHTMLVideoElement;
    onUnmute?: () => void;
}) => {
    // this is used to force a rerender
    const [, setMuted] = React.useState<boolean>();

    React.useEffect(() => {
        const handler = () => setMuted(video.muted);
        video.addEventListener('volumechange', handler);
        setMuted(video.muted);
        return () => video.removeEventListener('volumechange', handler);
    });

    return (
        <Stack spacing={0.5} direction="row" sx={{alignItems: 'center', my: 1, height: 35, pr: 2}}>
            <IconButton
                size="large"
                onClick={() => {
                    video.muted = !video.muted;
                    if (!video.muted && onUnmute) {
                        onUnmute();
                    }
                }}
            >
                {video.muted ? (
                    <VolumeMuteIcon fontSize="large" />
                ) : (
                    <VolumeIcon fontSize="large" />
                )}
            </IconButton>
            <Slider
                min={0}
                max={1}
                step={0.01}
                defaultValue={video.volume}
                onChange={(_, newVolume) => {
                    video.muted = false;
                    video.volume = Array.isArray(newVolume) ? newVolume[0] : newVolume;
                    if (onUnmute) {
                        onUnmute();
                    }
                }}
            />
        </Stack>
    );
};

const useStyles = makeStyles()(() => ({
    title: {
        padding: 15,
        position: 'fixed',
        top: '30px',
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 30,
    },
    bottomContainer: {
        position: 'fixed',
        display: 'flex',
        bottom: 0,
        right: 0,
        zIndex: 20,
    },
    control: {
        padding: 15,
        position: 'fixed',
        bottom: '30px',
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 30,
    },
    video: {
        display: 'block',
        margin: '0 auto',

        '&::-webkit-media-controls-start-playback-button': {
            display: 'none!important',
        },
        '&::-webkit-media-controls': {
            display: 'none!important',
        },
    },
    smallVideo: {
        minWidth: '100%',
        minHeight: '100%',
        width: 'auto',
        maxWidth: '300px',

        maxHeight: '200px',
    },
    videoWindowFit: {
        width: '100%',
        height: '100%',

        position: 'absolute',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%,-50%)',
    },
    videoWindowWidth: {
        height: 'auto',
        width: '100%',
    },
    videoWindowHeight: {
        height: '100%',
        width: 'auto',
    },
    smallVideoLabel: {
        position: 'absolute',
        display: 'block',
        bottom: 0,
        background: 'rgba(0,0,0,.5)',
        padding: '5px 15px',
    },
    noMaxWidth: {
        maxWidth: 'none',
    },
    smallVideoContainer: {
        height: '100%',
        padding: 5,
        maxHeight: 200,
        maxWidth: 400,
        width: '100%',
    },
    videoContainer: {
        position: 'absolute',
        top: 0,
        bottom: 0,
        width: '100%',
        height: '100%',

        overflow: 'auto',
    },
}));