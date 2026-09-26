package dev.arena.voicemusic.audio;

import com.sedmelluq.discord.lavaplayer.player.AudioPlayerManager;
import com.sedmelluq.discord.lavaplayer.track.AudioTrack;
import de.maxhenkel.voicechat.api.Group;
import de.maxhenkel.voicechat.api.VoicechatConnection;
import de.maxhenkel.voicechat.api.VoicechatServerApi;
import de.maxhenkel.voicechat.api.audiochannel.StaticAudioChannel;
import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.UUID;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class GroupMusicSessionTest {
    @Test void onlyMembersOfTheExactUuidGroupBecomeAudioTargets() {
        var groupId = UUID.randomUUID();
        var otherGroupId = UUID.randomUUID();
        var playerId = UUID.randomUUID();
        var outsiderId = UUID.randomUUID();
        Group group = mock(Group.class), other = mock(Group.class);
        when(group.getId()).thenReturn(groupId); when(group.getName()).thenReturn("friends");
        when(other.getId()).thenReturn(otherGroupId);
        Group sameUuidDifferentObject = mock(Group.class);
        when(sameUuidDifferentObject.getId()).thenReturn(new UUID(groupId.getMostSignificantBits(), groupId.getLeastSignificantBits()));
        VoicechatConnection member = connection(playerId, sameUuidDifferentObject);
        VoicechatConnection outsider = connection(outsiderId, other);
        VoicechatServerApi api = mock(VoicechatServerApi.class);
        when(api.getConnectionOf(playerId)).thenReturn(member);
        when(api.getConnectionOf(outsiderId)).thenReturn(outsider);
        StaticAudioChannel channel = mock(StaticAudioChannel.class);
        when(api.createStaticAudioChannel(any())).thenReturn(channel);
        AudioPlayerManager manager = mock(AudioPlayerManager.class);
        var player = mock(com.sedmelluq.discord.lavaplayer.player.AudioPlayer.class);
        when(manager.createPlayer()).thenReturn(player);

        var session = new GroupMusicSession(group, api, manager, 4, 80, () -> List.of(playerId, outsiderId), ignored -> { });
        verify(channel).addTarget(member);
        verify(channel, never()).addTarget(outsider);
        verify(channel).setBypassGroupIsolation(false);
        assertEquals(1, session.memberCount());

        VoicechatConnection lateOutsider = connection(UUID.randomUUID(), other);
        session.memberJoined(lateOutsider);
        session.memberJoined(member);
        verify(channel, never()).addTarget(lateOutsider);
        verify(channel, times(1)).addTarget(member);
        session.memberLeft(member);
        session.memberLeft(member);
        verify(channel, times(1)).removeTarget(member);
        assertEquals(0, session.memberCount());
        session.close();
        assertTrue(session.isClosed());
    }


    @Test void boundedQueueAndStopRestorePlayableState() {
        Group group = mock(Group.class);
        when(group.getId()).thenReturn(UUID.randomUUID()); when(group.getName()).thenReturn("queue");
        VoicechatServerApi api = mock(VoicechatServerApi.class);
        when(api.createStaticAudioChannel(any())).thenReturn(mock(StaticAudioChannel.class));
        AudioPlayerManager manager = mock(AudioPlayerManager.class);
        var player = mock(com.sedmelluq.discord.lavaplayer.player.AudioPlayer.class);
        when(manager.createPlayer()).thenReturn(player);
        GroupMusicSession session = new GroupMusicSession(group, api, manager, 2, 80, List::of, ignored -> { });
        verify(player).setVolume(80);

        assertTrue(session.enqueue(mock(AudioTrack.class)));
        assertTrue(session.pause());
        assertTrue(session.enqueue(mock(AudioTrack.class)));
        assertTrue(session.enqueue(mock(AudioTrack.class)));
        assertFalse(session.enqueue(mock(AudioTrack.class)));
        assertEquals(2, session.queuedCount());
        session.stop();
        assertEquals(0, session.queuedCount());
        assertFalse(session.pause());
        assertFalse(session.resume());
        verify(player).stopTrack();
        verify(player, times(2)).setPaused(false);
        session.close();
    }

    @Test void emptySessionsExpireOnlyAfterGracePeriod() {
        var group = mock(Group.class);
        when(group.getId()).thenReturn(UUID.randomUUID()); when(group.getName()).thenReturn("empty");
        var api = mock(VoicechatServerApi.class);
        var channel = mock(StaticAudioChannel.class);
        when(api.createStaticAudioChannel(any())).thenReturn(channel);
        var manager = mock(AudioPlayerManager.class);
        when(manager.createPlayer()).thenReturn(mock(com.sedmelluq.discord.lavaplayer.player.AudioPlayer.class));
        var session = new GroupMusicSession(group, api, manager, 4, 80, List::of, ignored -> { });
        assertFalse(session.shouldExpire(System.nanoTime(), java.time.Duration.ofHours(1).toNanos()));
        assertTrue(session.shouldExpire(System.nanoTime() + java.time.Duration.ofMinutes(3).toNanos(), java.time.Duration.ofMinutes(2).toNanos()));
        session.close();
    }

    private static VoicechatConnection connection(UUID playerId, Group group) {
        var connection = mock(VoicechatConnection.class);
        when(connection.getPlayerUuid()).thenReturn(playerId);
        when(connection.getGroup()).thenReturn(group);
        when(connection.isConnected()).thenReturn(true);
        return connection;
    }
}
