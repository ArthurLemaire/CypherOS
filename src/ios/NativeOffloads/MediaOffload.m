//
//  MediaOffload.m
//  MinisApp
//
//  Native offload handler for `apple-media`.
//  Subcommands: now-playing, play, pause, toggle, next, prev, volume, search, play-search
//

#import <Foundation/Foundation.h>
#import <MediaPlayer/MediaPlayer.h>
#import <UIKit/UIKit.h>
#import <AVFoundation/AVFoundation.h>
#import "NativeOffloadUtils.h"
#include "kernel/native_offload.h"
#include <unistd.h>

static NSString *const TOOL_NAME = @"apple-media";

static NSString *const HELP_TEXT =
    @"apple-media - Control iOS music playback and search the media library\n"
     "\n"
     "USAGE:\n"
     "  apple-media [command] [options]\n"
     "\n"
     "COMMANDS:\n"
     "  now-playing  Get currently playing track info (default when no command given)\n"
     "  play         Resume playback\n"
     "  pause        Pause playback\n"
     "  toggle       Toggle play/pause\n"
     "  next         Skip to next track\n"
     "  prev         Skip to previous track\n"
     "  volume       Get or set system volume\n"
     "  search       Search the media library\n"
     "  play-search  Search and immediately play the first result\n"
     "\n"
     "COMMON OPTIONS:\n"
     "  --help, -h           Show this help message\n"
     "  --compact            Minimize JSON output\n"
     "  -q, --quiet          Output only data field\n"
     "\n"
     "VOLUME OPTIONS:\n"
     "  --set <0.0-1.0>      Set volume level\n"
     "\n"
     "SEARCH OPTIONS:\n"
     "  --query <text>       Search query (required)\n"
     "  --type <type>        song, album, artist, playlist (default: song)\n"
     "  --limit <N>          Maximum results (default: 100)\n"
     "\n"
     "PLAY-SEARCH OPTIONS:\n"
     "  --query <text>       Search query (required)\n"
     "  --type <type>        song, album, artist (default: song)\n"
     "\n"
     "EXAMPLES:\n"
     "  apple-media                    (same as: apple-media now-playing)\n"
     "  apple-media play\n"
     "  apple-media toggle\n"
     "  apple-media volume --set 0.5\n"
     "  apple-media search --query \"Beatles\" --type artist\n"
     "  apple-media play-search --query \"Bohemian Rhapsody\"\n";

// Serial queue to prevent concurrent authorization dialogs
static dispatch_queue_t authQueue(void) {
    static dispatch_queue_t q = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        q = dispatch_queue_create("com.openminis.media.auth", DISPATCH_QUEUE_SERIAL);
    });
    return q;
}

// Request media library authorization synchronously
static BOOL requestMediaAccess(NSString **outError) {
    __block MPMediaLibraryAuthorizationStatus status;

    dispatch_sync(authQueue(), ^{
        dispatch_semaphore_t sem = dispatch_semaphore_create(0);

        [MPMediaLibrary requestAuthorization:^(MPMediaLibraryAuthorizationStatus s) {
            status = s;
            dispatch_semaphore_signal(sem);
        }];
        dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 30 * NSEC_PER_SEC));
    });

    if (status != MPMediaLibraryAuthorizationStatusAuthorized) {
        if (outError) {
            *outError = @"Media library access not granted. "
                         "To grant access, open Settings > Privacy & Security > Media & Apple Music "
                         "and enable Minis.";
        }
        return NO;
    }
    return YES;
}

// Build a dict from an MPMediaItem
static NSDictionary *media_item_to_dict(MPMediaItem *item) {
    NSMutableDictionary *d = [NSMutableDictionary dictionary];
    d[@"title"] = item.title ?: [NSNull null];
    d[@"artist"] = item.artist ?: [NSNull null];
    d[@"album"] = item.albumTitle ?: [NSNull null];
    d[@"duration_seconds"] = @(item.playbackDuration);
    d[@"track_number"] = @(item.albumTrackNumber);
    d[@"genre"] = item.genre ?: [NSNull null];
    d[@"play_count"] = @(item.playCount);
    return d;
}

// Build a now-playing info dict from the current player state
static NSDictionary *now_playing_dict(void) {
    __block NSDictionary *result = nil;
    noff_dispatch_main_sync(^id{
        MPMusicPlayerController *player = [MPMusicPlayerController systemMusicPlayer];
        MPMediaItem *item = player.nowPlayingItem;

        NSMutableDictionary *d = [NSMutableDictionary dictionary];
        if (item) {
            d[@"title"] = item.title ?: [NSNull null];
            d[@"artist"] = item.artist ?: [NSNull null];
            d[@"album"] = item.albumTitle ?: [NSNull null];
            d[@"duration_seconds"] = @(item.playbackDuration);
            d[@"playback_time"] = @(player.currentPlaybackTime);
            d[@"artwork_available"] = @(item.artwork != nil);
        } else {
            d[@"title"] = [NSNull null];
            d[@"artist"] = [NSNull null];
            d[@"album"] = [NSNull null];
            d[@"duration_seconds"] = [NSNull null];
            d[@"playback_time"] = [NSNull null];
            d[@"artwork_available"] = @NO;
        }

        NSString *state;
        switch (player.playbackState) {
            case MPMusicPlaybackStatePlaying:          state = @"playing"; break;
            case MPMusicPlaybackStatePaused:           state = @"paused"; break;
            case MPMusicPlaybackStateStopped:          state = @"stopped"; break;
            case MPMusicPlaybackStateInterrupted:      state = @"interrupted"; break;
            case MPMusicPlaybackStateSeekingForward:   state = @"seeking_forward"; break;
            case MPMusicPlaybackStateSeekingBackward:  state = @"seeking_backward"; break;
            default:                                   state = @"unknown"; break;
        }
        d[@"playback_state"] = state;

        result = [d copy];
        return nil;
    });
    return result;
}

static int cmd_now_playing(int argc, char **argv, int stdout_fd, BOOL compact, BOOL quiet) {
    NSDictionary *data = now_playing_dict();
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"now-playing", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_play(int argc, char **argv, int stdout_fd, BOOL compact, BOOL quiet) {
    noff_dispatch_main_sync(^id{
        [[MPMusicPlayerController systemMusicPlayer] play];
        return nil;
    });
    NSDictionary *data = @{@"status": @"playing"};
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"play", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_pause(int argc, char **argv, int stdout_fd, BOOL compact, BOOL quiet) {
    noff_dispatch_main_sync(^id{
        [[MPMusicPlayerController systemMusicPlayer] pause];
        return nil;
    });
    NSDictionary *data = @{@"status": @"paused"};
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"pause", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_toggle(int argc, char **argv, int stdout_fd, BOOL compact, BOOL quiet) {
    __block NSString *newState = nil;
    noff_dispatch_main_sync(^id{
        MPMusicPlayerController *player = [MPMusicPlayerController systemMusicPlayer];
        if (player.playbackState == MPMusicPlaybackStatePlaying) {
            [player pause];
            newState = @"paused";
        } else {
            [player play];
            newState = @"playing";
        }
        return nil;
    });
    NSDictionary *data = @{@"status": newState};
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"toggle", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_next(int argc, char **argv, int stdout_fd, BOOL compact, BOOL quiet) {
    noff_dispatch_main_sync(^id{
        [[MPMusicPlayerController systemMusicPlayer] skipToNextItem];
        return nil;
    });
    // Brief wait for track to change
    usleep(300000);

    __block NSDictionary *np = nil;
    noff_dispatch_main_sync(^id{
        MPMediaItem *item = [MPMusicPlayerController systemMusicPlayer].nowPlayingItem;
        if (item) {
            np = @{
                @"title": item.title ?: [NSNull null],
                @"artist": item.artist ?: [NSNull null],
                @"album": item.albumTitle ?: [NSNull null],
            };
        }
        return nil;
    });

    NSDictionary *data = @{
        @"status": @"next",
        @"now_playing": np ?: [NSNull null],
    };
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"next", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_prev(int argc, char **argv, int stdout_fd, BOOL compact, BOOL quiet) {
    noff_dispatch_main_sync(^id{
        [[MPMusicPlayerController systemMusicPlayer] skipToPreviousItem];
        return nil;
    });
    // Brief wait for track to change
    usleep(300000);

    __block NSDictionary *np = nil;
    noff_dispatch_main_sync(^id{
        MPMediaItem *item = [MPMusicPlayerController systemMusicPlayer].nowPlayingItem;
        if (item) {
            np = @{
                @"title": item.title ?: [NSNull null],
                @"artist": item.artist ?: [NSNull null],
                @"album": item.albumTitle ?: [NSNull null],
            };
        }
        return nil;
    });

    NSDictionary *data = @{
        @"status": @"previous",
        @"now_playing": np ?: [NSNull null],
    };
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"prev", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_volume(int argc, char **argv, int stdout_fd, BOOL compact, BOOL quiet) {
    NSString *setStr = noff_find_arg(argc, argv, "--set");

    if (setStr) {
        float newVolume = [setStr floatValue];
        if (newVolume < 0.0f) newVolume = 0.0f;
        if (newVolume > 1.0f) newVolume = 1.0f;

        noff_dispatch_main_sync(^id{
            MPVolumeView *volumeView = [[MPVolumeView alloc] initWithFrame:CGRectZero];
            UISlider *volumeSlider = nil;
            for (UIView *view in volumeView.subviews) {
                if ([view isKindOfClass:[UISlider class]]) {
                    volumeSlider = (UISlider *)view;
                    break;
                }
            }
            if (volumeSlider) {
                volumeSlider.value = newVolume;
                [volumeSlider sendActionsForControlEvents:UIControlEventTouchUpInside];
            }
            return nil;
        });
        // Brief wait for volume change to take effect
        usleep(100000);
    }

    float currentVolume = [[AVAudioSession sharedInstance] outputVolume];

    NSDictionary *data = @{@"volume": @(currentVolume)};
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"volume", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_search(int argc, char **argv, int stdout_fd, int stderr_fd, BOOL compact, BOOL quiet) {
    NSString *authErr = nil;
    if (!requestMediaAccess(&authErr)) {
        NSDictionary *err = noff_json_error(TOOL_NAME, @"search",
                                             NOFF_ERR_AUTHORIZATION_DENIED, authErr);
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_AUTH_DENIED;
    }

    NSString *query = noff_find_arg(argc, argv, "--query");
    if (!query) {
        noff_emit_help(stderr_fd, HELP_TEXT);
        NSDictionary *err = noff_json_error(TOOL_NAME, @"search",
                                             NOFF_ERR_INVALID_ARGS,
                                             @"Required: --query");
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_INVALID_ARGS;
    }

    NSString *type = noff_find_arg(argc, argv, "--type") ?: @"song";
    NSString *limitStr = noff_find_arg(argc, argv, "--limit");
    NSInteger limit = limitStr ? [limitStr integerValue] : 100;

    MPMediaQuery *mediaQuery = nil;
    MPMediaPropertyPredicate *predicate = nil;

    if ([type isEqualToString:@"song"]) {
        mediaQuery = [MPMediaQuery songsQuery];
        predicate = [MPMediaPropertyPredicate predicateWithValue:query
                                                    forProperty:MPMediaItemPropertyTitle
                                                 comparisonType:MPMediaPredicateComparisonContains];
    } else if ([type isEqualToString:@"album"]) {
        mediaQuery = [MPMediaQuery albumsQuery];
        predicate = [MPMediaPropertyPredicate predicateWithValue:query
                                                    forProperty:MPMediaItemPropertyAlbumTitle
                                                 comparisonType:MPMediaPredicateComparisonContains];
    } else if ([type isEqualToString:@"artist"]) {
        mediaQuery = [MPMediaQuery artistsQuery];
        predicate = [MPMediaPropertyPredicate predicateWithValue:query
                                                    forProperty:MPMediaItemPropertyArtist
                                                 comparisonType:MPMediaPredicateComparisonContains];
    } else if ([type isEqualToString:@"playlist"]) {
        mediaQuery = [MPMediaQuery playlistsQuery];
        predicate = [MPMediaPropertyPredicate predicateWithValue:query
                                                    forProperty:MPMediaPlaylistPropertyName
                                                 comparisonType:MPMediaPredicateComparisonContains];
    } else {
        noff_emit_help(stderr_fd, HELP_TEXT);
        NSDictionary *err = noff_json_error(TOOL_NAME, @"search",
                                             NOFF_ERR_INVALID_ARGS,
                                             @"--type must be song, album, artist, or playlist");
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_INVALID_ARGS;
    }

    [mediaQuery addFilterPredicate:predicate];

    NSArray<MPMediaItem *> *items = mediaQuery.items ?: @[];
    NSInteger totalCount = (NSInteger)items.count;
    if (totalCount > limit) {
        items = [items subarrayWithRange:NSMakeRange(0, limit)];
    }

    NSMutableArray *results = [NSMutableArray array];
    for (MPMediaItem *item in items) {
        [results addObject:media_item_to_dict(item)];
    }

    NSMutableDictionary *data = [@{
        @"results": results,
        @"query": query,
        @"type": type,
        @"count": @(results.count),
    } mutableCopy];
    if (totalCount > limit) {
        data[@"_warning"] = [NSString stringWithFormat:
            @"Results truncated by --limit. Returned %ld of %ld total records. "
             "Use a larger --limit to retrieve more data.",
            (long)limit, (long)totalCount];
        data[@"total_available"] = @(totalCount);
    }
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"search", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_play_search(int argc, char **argv, int stdout_fd, int stderr_fd, BOOL compact, BOOL quiet) {
    NSString *authErr = nil;
    if (!requestMediaAccess(&authErr)) {
        NSDictionary *err = noff_json_error(TOOL_NAME, @"play-search",
                                             NOFF_ERR_AUTHORIZATION_DENIED, authErr);
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_AUTH_DENIED;
    }

    NSString *query = noff_find_arg(argc, argv, "--query");
    if (!query) {
        noff_emit_help(stderr_fd, HELP_TEXT);
        NSDictionary *err = noff_json_error(TOOL_NAME, @"play-search",
                                             NOFF_ERR_INVALID_ARGS,
                                             @"Required: --query");
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_INVALID_ARGS;
    }

    NSString *type = noff_find_arg(argc, argv, "--type") ?: @"song";

    MPMediaQuery *mediaQuery = nil;
    MPMediaPropertyPredicate *predicate = nil;

    if ([type isEqualToString:@"song"]) {
        mediaQuery = [MPMediaQuery songsQuery];
        predicate = [MPMediaPropertyPredicate predicateWithValue:query
                                                    forProperty:MPMediaItemPropertyTitle
                                                 comparisonType:MPMediaPredicateComparisonContains];
    } else if ([type isEqualToString:@"album"]) {
        mediaQuery = [MPMediaQuery albumsQuery];
        predicate = [MPMediaPropertyPredicate predicateWithValue:query
                                                    forProperty:MPMediaItemPropertyAlbumTitle
                                                 comparisonType:MPMediaPredicateComparisonContains];
    } else if ([type isEqualToString:@"artist"]) {
        mediaQuery = [MPMediaQuery artistsQuery];
        predicate = [MPMediaPropertyPredicate predicateWithValue:query
                                                    forProperty:MPMediaItemPropertyArtist
                                                 comparisonType:MPMediaPredicateComparisonContains];
    } else {
        noff_emit_help(stderr_fd, HELP_TEXT);
        NSDictionary *err = noff_json_error(TOOL_NAME, @"play-search",
                                             NOFF_ERR_INVALID_ARGS,
                                             @"--type must be song, album, or artist");
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_INVALID_ARGS;
    }

    [mediaQuery addFilterPredicate:predicate];

    NSArray<MPMediaItem *> *items = mediaQuery.items;
    if (!items || items.count == 0) {
        NSDictionary *err = noff_json_error(TOOL_NAME, @"play-search",
                                             NOFF_ERR_NO_DATA,
                                             [NSString stringWithFormat:@"No results for '%@'", query]);
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_ERROR;
    }

    noff_dispatch_main_sync(^id{
        MPMusicPlayerController *player = [MPMusicPlayerController systemMusicPlayer];
        [player setQueueWithQuery:mediaQuery];
        [player play];
        return nil;
    });

    // Brief wait for playback to start
    usleep(300000);

    __block NSDictionary *np = nil;
    noff_dispatch_main_sync(^id{
        MPMediaItem *item = [MPMusicPlayerController systemMusicPlayer].nowPlayingItem;
        if (item) {
            np = @{
                @"title": item.title ?: [NSNull null],
                @"artist": item.artist ?: [NSNull null],
                @"album": item.albumTitle ?: [NSNull null],
            };
        }
        return nil;
    });

    NSDictionary *data = @{
        @"status": @"playing",
        @"now_playing": np ?: [NSNull null],
    };
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"play-search", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int media_handler(int argc, char **argv,
                          int stdin_fd, int stdout_fd, int stderr_fd) {
    if (noff_has_flag(argc, argv, "--help") || noff_has_flag(argc, argv, "-h")) {
        noff_emit_help(stderr_fd, HELP_TEXT);
        return NOFF_EXIT_SUCCESS;
    }

    BOOL compact = noff_has_flag(argc, argv, "--compact");
    BOOL quiet = noff_has_flag(argc, argv, "-q") || noff_has_flag(argc, argv, "--quiet");

    NSString *subcmd = noff_get_subcommand(argc, argv);
    if (!subcmd) {
        // [T-offload-defaults-batch-ios] Bare `apple-media` (including
        // flags-only invocations) defaults to `now-playing` — a read-only
        // status query; never silently mutates playback.
        subcmd = @"now-playing";
    }

    if ([subcmd isEqualToString:@"now-playing"])  return cmd_now_playing(argc, argv, stdout_fd, compact, quiet);
    if ([subcmd isEqualToString:@"play"])          return cmd_play(argc, argv, stdout_fd, compact, quiet);
    if ([subcmd isEqualToString:@"pause"])         return cmd_pause(argc, argv, stdout_fd, compact, quiet);
    if ([subcmd isEqualToString:@"toggle"])        return cmd_toggle(argc, argv, stdout_fd, compact, quiet);
    if ([subcmd isEqualToString:@"next"])          return cmd_next(argc, argv, stdout_fd, compact, quiet);
    if ([subcmd isEqualToString:@"prev"])          return cmd_prev(argc, argv, stdout_fd, compact, quiet);
    if ([subcmd isEqualToString:@"volume"])        return cmd_volume(argc, argv, stdout_fd, compact, quiet);
    if ([subcmd isEqualToString:@"search"])        return cmd_search(argc, argv, stdout_fd, stderr_fd, compact, quiet);
    if ([subcmd isEqualToString:@"play-search"])   return cmd_play_search(argc, argv, stdout_fd, stderr_fd, compact, quiet);

    noff_emit_help(stderr_fd, HELP_TEXT);
    NSDictionary *err = noff_json_error(TOOL_NAME, subcmd,
                                         NOFF_ERR_INVALID_ARGS,
                                         [NSString stringWithFormat:@"Unknown command '%@'. Valid commands: now-playing, play, pause, toggle, next, prev, volume, search, play-search. Use --help for details.", subcmd]);
    noff_emit_json(stdout_fd, err, compact, quiet);
    return NOFF_EXIT_INVALID_ARGS;
}

void media_offload_register(void) {
    int err = native_offload_add_handler("apple-media", media_handler);
    if (err == 0) {
        noff_ensure_guest_stub("/usr/local/bin/apple-media");
        NSLog(@"NativeOffloads: apple-media handler registered");
    } else {
        NSLog(@"NativeOffloads: failed to register apple-media handler (err=%d)", err);
    }
}
