import React from 'react';
import {
    Box,
    Button,
    FormControl,
    Grid,
    Paper,
    TextField,
} from '@mui/material';
import {FCreateRoom, UseRoom} from './useRoom';
import {UIConfig} from './message';
import {getRoomFromURL} from './useRoomID';
import {authModeToRoomMode, UseConfig} from './useConfig';

const CreateRoom = ({room, config}: Pick<UseRoom, 'room'> & {config: UIConfig}) => {
    const [id, setId] = React.useState(() => getRoomFromURL() ?? config.roomName);
    const mode = authModeToRoomMode(config.authMode, config.loggedIn);
    const submit = () =>
        room({
            type: 'create',
            payload: {
                mode,
                closeOnOwnerLeave: config.closeRoomWhenOwnerLeaves,
                joinIfExist: true,
                id: id || undefined,
            },
        });
    return (
        <div>
            <FormControl fullWidth>
                <TextField
                    fullWidth
                    value={id}
                    onChange={(e) => setId(e.target.value)}
                    label="id"
                    margin="dense"
                />
                <Box sx={{marginTop: 2}}>
                    <Button onClick={submit} fullWidth variant="contained">
                        Create or Join a Room
                    </Button>
                </Box>
            </FormControl>
        </div>
    );
};

export const RoomManage = ({room, config}: {room: FCreateRoom; config: UseConfig}) => {
    return (
        <Grid
            container={true}
            sx={{justifyContent: 'center'}}
            style={{paddingTop: 50, maxWidth: 400, width: '100%', margin: '0 auto'}}
            spacing={4}
        >
            <Grid size={12} sx={{ width: '100%' }}>
                <Paper elevation={3} style={{padding: 20}}>
                    <CreateRoom room={room} config={config} />
                </Paper>
            </Grid>
        </Grid>
    );
};