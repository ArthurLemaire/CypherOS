//
//  RemindersOffload.m
//  MinisApp
//
//  Native offload handler for `apple-reminders`.
//  Delegates to the shared reminder implementations in CalendarOffload.
//  Subcommands: list, create, update, complete, delete
//

#import <Foundation/Foundation.h>
#import "NativeOffloadUtils.h"
#import "CalendarOffload.h"
#include "kernel/native_offload.h"

static NSString *const TOOL_NAME = @"apple-reminders";

static NSString *const HELP_TEXT =
    @"apple-reminders - Query and manage iOS reminders\n"
     "\n"
     "USAGE:\n"
     "  apple-reminders <command> [options]\n"
     "\n"
     "COMMANDS:\n"
     "  list        List reminders\n"
     "  create      Create a new reminder\n"
     "  update      Update an existing reminder\n"
     "  complete    Mark a reminder as completed\n"
     "  delete      Delete a reminder\n"
     "\n"
     "COMMON OPTIONS:\n"
     "  --help, -h           Show this help message\n"
     "  --compact            Minimize JSON output\n"
     "  -q, --quiet          Output only data field\n"
     "\n"
     "LIST OPTIONS:\n"
     "  --completed          Show only completed reminders\n"
     "  --incomplete         Show only incomplete reminders\n"
     "  --list <name>        Filter by reminder list name\n"
     "  --limit <N>          Maximum number of results\n"
     "\n"
     "CREATE OPTIONS:\n"
     "  --title <title>      Reminder title (required)\n"
     "  --due <datetime>     Due date (ISO 8601 or relative)\n"
     "  --list <name>        Reminder list name\n"
     "  --priority <0-9>     Priority level\n"
     "  --notes <text>       Reminder notes\n"
     "  --parent-id <id>     (Unsupported) Subtasks have no public EventKit API\n"
     "                       on iOS through 26.5; passing this returns an error.\n"
     "\n"
     "UPDATE OPTIONS:\n"
     "  --id <reminder_id>   Reminder ID (required, from list output)\n"
     "  --title <title>      New title\n"
     "  --due <datetime>     New due date\n"
     "  --list <name>        Move to a different list\n"
     "  --priority <0-9>     New priority\n"
     "  --notes <text>       New notes\n"
     "\n"
     "COMPLETE OPTIONS:\n"
     "  --id <reminder_id>   Reminder ID (required, from list output)\n"
     "  --undo               Mark as incomplete instead\n"
     "\n"
     "DELETE OPTIONS:\n"
     "  --id <reminder_id>   Reminder ID (required, from list output)\n"
     "\n"
     "EXAMPLES:\n"
     "  apple-reminders list\n"
     "  apple-reminders list --incomplete --limit 10\n"
     "  apple-reminders list --list \"Shopping\"\n"
     "  apple-reminders create --title \"Buy groceries\" --due 2026-02-25T18:00\n"
     "  apple-reminders update --id <reminder_id> --title \"New title\" --due 2026-03-01T10:00\n"
     "  apple-reminders complete --id <reminder_id>\n"
     "  apple-reminders complete --id <reminder_id> --undo\n"
     "  apple-reminders delete --id <reminder_id>\n";

static int reminders_handler(int argc, char **argv,
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

    if ([subcmd isEqualToString:@"list"])     return calendar_cmd_reminders(argc, argv, stdout_fd, compact, quiet);
    if ([subcmd isEqualToString:@"create"])   return calendar_cmd_remind(argc, argv, stdout_fd, stderr_fd, compact, quiet);
    if ([subcmd isEqualToString:@"update"])   return calendar_cmd_update_reminder(argc, argv, stdout_fd, compact, quiet);
    if ([subcmd isEqualToString:@"complete"]) return calendar_cmd_complete_reminder(argc, argv, stdout_fd, compact, quiet);
    if ([subcmd isEqualToString:@"delete"])   return calendar_cmd_delete_reminder(argc, argv, stdout_fd, compact, quiet);

    noff_emit_help(stderr_fd, HELP_TEXT);
    NSDictionary *err = noff_json_error(TOOL_NAME, subcmd,
                                         NOFF_ERR_INVALID_ARGS,
                                         [NSString stringWithFormat:@"Unknown command '%@'. Valid commands: list, create, update, complete, delete. Use --help for details.", subcmd]);
    noff_emit_json(stdout_fd, err, compact, quiet);
    return NOFF_EXIT_INVALID_ARGS;
}

void reminders_offload_register(void) {
    int err = native_offload_add_handler("apple-reminders", reminders_handler);
    if (err == 0) {
        noff_ensure_guest_stub("/usr/local/bin/apple-reminders");
        NSLog(@"NativeOffloads: apple-reminders handler registered");
    } else {
        NSLog(@"NativeOffloads: failed to register apple-reminders handler (err=%d)", err);
    }
}
