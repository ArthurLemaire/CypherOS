//
//  NotificationOffload.m
//  MinisApp
//
//  Native offload handler for `apple-notification`.
//  Subcommands: pending, delivered, settings, schedule, cancel
//

#import <Foundation/Foundation.h>
#import <UserNotifications/UserNotifications.h>
#import "NativeOffloadUtils.h"
#include "kernel/native_offload.h"
#include <unistd.h>

static NSString *const TOOL_NAME = @"apple-notification";

static NSString *const HELP_TEXT =
    @"apple-notification - Manage local notifications\n"
     "\n"
     "USAGE:\n"
     "  apple-notification <command> [options]\n"
     "\n"
     "COMMANDS:\n"
     "  pending     List pending (scheduled) notifications\n"
     "  delivered   List delivered notifications\n"
     "  settings    Get notification authorization status and settings\n"
     "  schedule    Schedule a local notification\n"
     "  cancel      Cancel pending notification(s)\n"
     "\n"
     "OPTIONS:\n"
     "  --help, -h          Show this help message\n"
     "  --compact           Minimize JSON output\n"
     "  -q, --quiet         Output only data field\n"
     "  --title <text>      Notification title (for schedule)\n"
     "  --body <text>       Notification body (for schedule)\n"
     "  --after <seconds>   Schedule after N seconds (for schedule)\n"
     "  --at <time>         Schedule at ISO time (for schedule)\n"
     "  --id <identifier>   Notification identifier (for cancel)\n"
     "  --all               Cancel all pending notifications\n"
     "\n"
     "EXAMPLES:\n"
     "  apple-notification settings\n"
     "  apple-notification pending\n"
     "  apple-notification schedule --title \"Reminder\" --body \"Check task\" --after 300\n"
     "  apple-notification schedule --title \"Meeting\" --body \"Standup\" --at 2024-01-15T09:00:00\n"
     "  apple-notification cancel --id my-reminder\n"
     "  apple-notification cancel --all\n";

static NSString *auth_status_string(UNAuthorizationStatus status) {
    switch (status) {
        case UNAuthorizationStatusAuthorized:    return @"authorized";
        case UNAuthorizationStatusDenied:        return @"denied";
        case UNAuthorizationStatusNotDetermined: return @"not_determined";
        case UNAuthorizationStatusProvisional:   return @"provisional";
        case UNAuthorizationStatusEphemeral:     return @"ephemeral";
        default: return @"unknown";
    }
}

static NSDictionary *request_to_dict(UNNotificationRequest *req) {
    NSMutableDictionary *d = [NSMutableDictionary dictionary];
    d[@"id"] = req.identifier;
    d[@"title"] = req.content.title ?: @"";
    d[@"body"] = req.content.body ?: @"";
    d[@"subtitle"] = req.content.subtitle ?: @"";
    if (req.content.userInfo.count > 0) {
        d[@"user_info"] = req.content.userInfo;
    }

    if ([req.trigger isKindOfClass:[UNTimeIntervalNotificationTrigger class]]) {
        UNTimeIntervalNotificationTrigger *t = (UNTimeIntervalNotificationTrigger *)req.trigger;
        d[@"trigger_type"] = @"time_interval";
        d[@"trigger_interval_sec"] = @(t.timeInterval);
        d[@"trigger_repeats"] = @(t.repeats);
        if (t.nextTriggerDate) {
            d[@"next_trigger_date"] = noff_format_date(t.nextTriggerDate);
        }
    } else if ([req.trigger isKindOfClass:[UNCalendarNotificationTrigger class]]) {
        UNCalendarNotificationTrigger *t = (UNCalendarNotificationTrigger *)req.trigger;
        d[@"trigger_type"] = @"calendar";
        d[@"trigger_repeats"] = @(t.repeats);
        if (t.nextTriggerDate) {
            d[@"next_trigger_date"] = noff_format_date(t.nextTriggerDate);
        }
    }

    return d;
}

static NSDictionary *notification_to_dict(UNNotification *notif) {
    NSMutableDictionary *d = [NSMutableDictionary dictionaryWithDictionary:request_to_dict(notif.request)];
    d[@"date"] = noff_format_date(notif.date);
    return d;
}

static int cmd_settings(int stdout_fd, BOOL compact, BOOL quiet) {
    UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];
    dispatch_semaphore_t sem = dispatch_semaphore_create(0);
    __block UNNotificationSettings *settings = nil;

    [center getNotificationSettingsWithCompletionHandler:^(UNNotificationSettings *s) {
        settings = s;
        dispatch_semaphore_signal(sem);
    }];

    dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC));

    if (!settings) {
        NSDictionary *err = noff_json_error(TOOL_NAME, @"settings",
                                             NOFF_ERR_NOT_AVAILABLE,
                                             @"Failed to get notification settings");
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_NOT_AVAILABLE;
    }

    NSDictionary *data = @{
        @"authorization_status": auth_status_string(settings.authorizationStatus),
        @"sound_enabled": @(settings.soundSetting == UNNotificationSettingEnabled),
        @"badge_enabled": @(settings.badgeSetting == UNNotificationSettingEnabled),
        @"alert_enabled": @(settings.alertSetting == UNNotificationSettingEnabled),
        @"lock_screen_enabled": @(settings.lockScreenSetting == UNNotificationSettingEnabled),
        @"notification_center_enabled": @(settings.notificationCenterSetting == UNNotificationSettingEnabled),
        @"critical_alert_enabled": @(settings.criticalAlertSetting == UNNotificationSettingEnabled),
    };

    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"settings", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_pending(int stdout_fd, BOOL compact, BOOL quiet) {
    UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];
    dispatch_semaphore_t sem = dispatch_semaphore_create(0);
    __block NSArray<UNNotificationRequest *> *requests = nil;

    [center getPendingNotificationRequestsWithCompletionHandler:^(NSArray<UNNotificationRequest *> *reqs) {
        requests = reqs;
        dispatch_semaphore_signal(sem);
    }];

    dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC));

    NSMutableArray *items = [NSMutableArray array];
    for (UNNotificationRequest *req in requests ?: @[]) {
        [items addObject:request_to_dict(req)];
    }

    NSDictionary *data = @{
        @"notifications": items,
        @"count": @(items.count),
    };
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"pending", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_delivered(int stdout_fd, BOOL compact, BOOL quiet) {
    UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];
    dispatch_semaphore_t sem = dispatch_semaphore_create(0);
    __block NSArray<UNNotification *> *notifications = nil;

    [center getDeliveredNotificationsWithCompletionHandler:^(NSArray<UNNotification *> *notifs) {
        notifications = notifs;
        dispatch_semaphore_signal(sem);
    }];

    dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC));

    NSMutableArray *items = [NSMutableArray array];
    for (UNNotification *notif in notifications ?: @[]) {
        [items addObject:notification_to_dict(notif)];
    }

    NSDictionary *data = @{
        @"notifications": items,
        @"count": @(items.count),
    };
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"delivered", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_schedule(int argc, char **argv, int stdout_fd, int stderr_fd, BOOL compact, BOOL quiet) {
    NSString *title = noff_find_arg(argc, argv, "--title");
    NSString *body = noff_find_arg(argc, argv, "--body");

    if (!title || !body) {
        noff_emit_help(stderr_fd, HELP_TEXT);
        NSDictionary *err = noff_json_error(TOOL_NAME, @"schedule",
                                             NOFF_ERR_INVALID_ARGS,
                                             @"--title and --body are required.");
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_INVALID_ARGS;
    }

    NSString *afterStr = noff_find_arg(argc, argv, "--after");
    NSString *atStr = noff_find_arg(argc, argv, "--at");

    if (!afterStr && !atStr) {
        noff_emit_help(stderr_fd, HELP_TEXT);
        NSDictionary *err = noff_json_error(TOOL_NAME, @"schedule",
                                             NOFF_ERR_INVALID_ARGS,
                                             @"Specify --after <seconds> or --at <time>.");
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_INVALID_ARGS;
    }

    UNMutableNotificationContent *content = [[UNMutableNotificationContent alloc] init];
    content.title = title;
    content.body = body;
    content.sound = [UNNotificationSound defaultSound];

    UNNotificationTrigger *trigger = nil;
    NSString *scheduleDesc = nil;

    if (afterStr) {
        NSTimeInterval interval = [afterStr doubleValue];
        if (interval <= 0) interval = 1;
        trigger = [UNTimeIntervalNotificationTrigger triggerWithTimeInterval:interval repeats:NO];
        scheduleDesc = [NSString stringWithFormat:@"in %.0f seconds", interval];
    } else {
        NSDate *date = noff_parse_date(atStr);
        if (!date) {
            noff_emit_help(stderr_fd, HELP_TEXT);
            NSDictionary *err = noff_json_error(TOOL_NAME, @"schedule",
                                                 NOFF_ERR_INVALID_ARGS,
                                                 @"Could not parse --at date. Use ISO 8601 format.");
            noff_emit_json(stdout_fd, err, compact, quiet);
            return NOFF_EXIT_INVALID_ARGS;
        }
        NSDateComponents *comps = [[NSCalendar currentCalendar]
            components:(NSCalendarUnitYear | NSCalendarUnitMonth | NSCalendarUnitDay |
                        NSCalendarUnitHour | NSCalendarUnitMinute | NSCalendarUnitSecond)
              fromDate:date];
        trigger = [UNCalendarNotificationTrigger triggerWithDateMatchingComponents:comps repeats:NO];
        scheduleDesc = [NSString stringWithFormat:@"at %@", noff_format_date(date)];
    }

    NSString *identifier = [[NSUUID UUID] UUIDString];
    UNNotificationRequest *request = [UNNotificationRequest requestWithIdentifier:identifier
                                                                          content:content
                                                                          trigger:trigger];

    UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];
    __block NSError *addError = nil;

    // Ensure authorization first (serialized to prevent concurrent dialog race)
    static dispatch_queue_t notifAuthQueue = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        notifAuthQueue = dispatch_queue_create("com.openminis.notification.auth", DISPATCH_QUEUE_SERIAL);
    });

    __block BOOL granted = NO;
    dispatch_sync(notifAuthQueue, ^{
        dispatch_semaphore_t sem = dispatch_semaphore_create(0);
        [center requestAuthorizationWithOptions:(UNAuthorizationOptionAlert | UNAuthorizationOptionSound | UNAuthorizationOptionBadge)
                              completionHandler:^(BOOL g, NSError *e) {
            granted = g;
            dispatch_semaphore_signal(sem);
        }];
        dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 30 * NSEC_PER_SEC));
    });

    if (!granted) {
        NSDictionary *err = noff_json_error(TOOL_NAME, @"schedule",
                                             NOFF_ERR_AUTHORIZATION_DENIED,
                                             @"Notification permission not granted. "
                                              "To grant access, open Settings > Notifications > Minis "
                                              "and enable notifications.");
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_AUTH_DENIED;
    }

    dispatch_semaphore_t sem = dispatch_semaphore_create(0);
    [center addNotificationRequest:request withCompletionHandler:^(NSError *error) {
        addError = error;
        dispatch_semaphore_signal(sem);
    }];
    dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC));

    if (addError) {
        NSDictionary *err = noff_json_error(TOOL_NAME, @"schedule",
                                             NOFF_ERR_INTERNAL_ERROR,
                                             addError.localizedDescription);
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_ERROR;
    }

    NSDictionary *data = @{
        @"id": identifier,
        @"title": title,
        @"body": body,
        @"scheduled": scheduleDesc,
    };
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"schedule", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_cancel(int argc, char **argv, int stdout_fd, int stderr_fd, BOOL compact, BOOL quiet) {
    BOOL cancelAll = noff_has_flag(argc, argv, "--all");
    NSString *identifier = noff_find_arg(argc, argv, "--id");

    if (!cancelAll && !identifier) {
        noff_emit_help(stderr_fd, HELP_TEXT);
        NSDictionary *err = noff_json_error(TOOL_NAME, @"cancel",
                                             NOFF_ERR_INVALID_ARGS,
                                             @"Specify --id <identifier> or --all.");
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_INVALID_ARGS;
    }

    UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];

    if (cancelAll) {
        [center removeAllPendingNotificationRequests];
        NSDictionary *data = @{@"cancelled": @"all"};
        noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"cancel", data), compact, quiet);
    } else {
        [center removePendingNotificationRequestsWithIdentifiers:@[identifier]];
        NSDictionary *data = @{@"cancelled": identifier};
        noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"cancel", data), compact, quiet);
    }

    return NOFF_EXIT_SUCCESS;
}

static int notification_handler(int argc, char **argv,
                                 int stdin_fd, int stdout_fd, int stderr_fd) {
    if (noff_has_flag(argc, argv, "--help") || noff_has_flag(argc, argv, "-h")) {
        noff_emit_help(stderr_fd, HELP_TEXT);
        return NOFF_EXIT_SUCCESS;
    }

    BOOL compact = noff_has_flag(argc, argv, "--compact");
    BOOL quiet = noff_has_flag(argc, argv, "-q") || noff_has_flag(argc, argv, "--quiet");

    NSString *subcmd = noff_get_subcommand(argc, argv);
    if (!subcmd) {
        noff_emit_help(stderr_fd, HELP_TEXT);
        NSDictionary *err = noff_json_error(TOOL_NAME, @"unknown",
                                             NOFF_ERR_INVALID_ARGS,
                                             @"No command specified. Use --help for usage.");
        noff_emit_json(stdout_fd, err, compact, quiet);
        return NOFF_EXIT_INVALID_ARGS;
    }

    if ([subcmd isEqualToString:@"pending"]) {
        return cmd_pending(stdout_fd, compact, quiet);
    } else if ([subcmd isEqualToString:@"delivered"]) {
        return cmd_delivered(stdout_fd, compact, quiet);
    } else if ([subcmd isEqualToString:@"settings"]) {
        return cmd_settings(stdout_fd, compact, quiet);
    } else if ([subcmd isEqualToString:@"schedule"]) {
        return cmd_schedule(argc, argv, stdout_fd, stderr_fd, compact, quiet);
    } else if ([subcmd isEqualToString:@"cancel"]) {
        return cmd_cancel(argc, argv, stdout_fd, stderr_fd, compact, quiet);
    }

    noff_emit_help(stderr_fd, HELP_TEXT);
    NSDictionary *err = noff_json_error(TOOL_NAME, subcmd,
                                         NOFF_ERR_INVALID_ARGS,
                                         [NSString stringWithFormat:@"Unknown command '%@'. Valid commands: schedule, pending, delivered, cancel, settings. Use --help for details.", subcmd]);
    noff_emit_json(stdout_fd, err, compact, quiet);
    return NOFF_EXIT_INVALID_ARGS;
}

void notification_offload_register(void) {
    int err = native_offload_add_handler("apple-notification", notification_handler);
    if (err == 0) {
        noff_ensure_guest_stub("/usr/local/bin/apple-notification");
        NSLog(@"NativeOffloads: apple-notification handler registered");
    } else {
        NSLog(@"NativeOffloads: failed to register apple-notification handler (err=%d)", err);
    }
}
