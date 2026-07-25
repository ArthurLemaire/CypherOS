//
//  DeviceOffload.m
//  MinisApp
//
//  Native offload handler for `apple-device`.
//  Subcommands: info, battery, storage
//

#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
#import "NativeOffloadUtils.h"
#include "kernel/native_offload.h"
#include <unistd.h>
#include <sys/utsname.h>
#include <mach/mach.h>

static NSString *const TOOL_NAME = @"apple-device";

static NSString *const HELP_TEXT =
    @"apple-device - Query device information\n"
     "\n"
     "USAGE:\n"
     "  apple-device [command] [options]\n"
     "\n"
     "COMMANDS:\n"
     "  info       Full device info (model, OS, CPU, memory, disk, network)\n"
     "             (default when no command given)\n"
     "  battery    Battery level and charging state\n"
     "  storage    Disk space information\n"
     "\n"
     "OPTIONS:\n"
     "  --help, -h      Show this help message\n"
     "  --compact       Minimize JSON output\n"
     "  -q, --quiet     Output only data field\n"
     "\n"
     "EXAMPLES:\n"
     "  apple-device                   (same as: apple-device info)\n"
     "  apple-device battery\n"
     "  apple-device storage --compact\n";

static NSString *thermal_state_string(NSProcessInfoThermalState state) {
    switch (state) {
        case NSProcessInfoThermalStateNominal:  return @"nominal";
        case NSProcessInfoThermalStateFair:     return @"fair";
        case NSProcessInfoThermalStateSerious:  return @"serious";
        case NSProcessInfoThermalStateCritical: return @"critical";
        default: return @"unknown";
    }
}

static NSString *battery_state_string(UIDeviceBatteryState state) {
    switch (state) {
        case UIDeviceBatteryStateUnplugged: return @"unplugged";
        case UIDeviceBatteryStateCharging:  return @"charging";
        case UIDeviceBatteryStateFull:      return @"full";
        default: return @"unknown";
    }
}

static NSDictionary *get_battery_data(void) {
    __block NSDictionary *data;
    noff_dispatch_main_sync(^id{
        UIDevice *dev = [UIDevice currentDevice];
        BOOL wasEnabled = dev.batteryMonitoringEnabled;
        dev.batteryMonitoringEnabled = YES;

        float level = dev.batteryLevel;
        UIDeviceBatteryState state = dev.batteryState;

        if (!wasEnabled) dev.batteryMonitoringEnabled = NO;

        data = @{
            @"level": level >= 0 ? @(level) : [NSNull null],
            @"level_percent": level >= 0 ? @((int)(level * 100)) : [NSNull null],
            @"state": battery_state_string(state),
            @"monitoring_enabled": @YES,
        };
        return nil;
    });
    return data;
}

static NSDictionary *get_storage_data(void) {
    NSError *error = nil;
    NSDictionary *attrs = [[NSFileManager defaultManager]
        attributesOfFileSystemForPath:NSHomeDirectory()
                                error:&error];
    if (!attrs) {
        return @{@"error": error.localizedDescription ?: @"unknown"};
    }

    unsigned long long totalSpace = [attrs[NSFileSystemSize] unsignedLongLongValue];
    unsigned long long freeSpace = [attrs[NSFileSystemFreeSize] unsignedLongLongValue];
    unsigned long long usedSpace = totalSpace - freeSpace;

    return @{
        @"total_bytes": @(totalSpace),
        @"free_bytes": @(freeSpace),
        @"used_bytes": @(usedSpace),
        @"total_gb": @(totalSpace / (1024.0 * 1024.0 * 1024.0)),
        @"free_gb": @(freeSpace / (1024.0 * 1024.0 * 1024.0)),
        @"used_gb": @(usedSpace / (1024.0 * 1024.0 * 1024.0)),
        @"usage_percent": totalSpace > 0 ? @((double)usedSpace / totalSpace * 100.0) : @(0),
    };
}

static int cmd_info(int stdout_fd, BOOL compact, BOOL quiet) {
    __block NSDictionary *deviceData;

    noff_dispatch_main_sync(^id{
        UIDevice *dev = [UIDevice currentDevice];
        deviceData = @{
            @"name": dev.name ?: @"",
            @"system_name": dev.systemName ?: @"",
            @"system_version": dev.systemVersion ?: @"",
            @"model": dev.model ?: @"",
            @"localized_model": dev.localizedModel ?: @"",
            @"identifier_for_vendor": dev.identifierForVendor.UUIDString ?: @"",
            @"user_interface_idiom": (dev.userInterfaceIdiom == UIUserInterfaceIdiomPad) ? @"pad" : @"phone",
        };
        return nil;
    });

    struct utsname sysinfo;
    uname(&sysinfo);
    NSString *machine = [NSString stringWithCString:sysinfo.machine encoding:NSUTF8StringEncoding];

    NSProcessInfo *pi = [NSProcessInfo processInfo];
    NSUInteger physMem = pi.physicalMemory;

    // Get active memory usage
    mach_task_basic_info_data_t taskInfo;
    mach_msg_type_number_t infoCount = MACH_TASK_BASIC_INFO_COUNT;
    kern_return_t kr = task_info(mach_task_self(), MACH_TASK_BASIC_INFO,
                                  (task_info_t)&taskInfo, &infoCount);
    NSNumber *appMemory = (kr == KERN_SUCCESS) ? @(taskInfo.resident_size) : [NSNull null];

    NSMutableDictionary *data = [NSMutableDictionary dictionary];
    data[@"device"] = deviceData;
    data[@"machine"] = machine ?: @"unknown";
    data[@"processor_count"] = @(pi.processorCount);
    data[@"active_processor_count"] = @(pi.activeProcessorCount);
    data[@"physical_memory_bytes"] = @(physMem);
    data[@"physical_memory_gb"] = @(physMem / (1024.0 * 1024.0 * 1024.0));
    data[@"app_memory_bytes"] = appMemory;
    data[@"thermal_state"] = thermal_state_string(pi.thermalState);
    data[@"is_low_power_mode"] = @(pi.isLowPowerModeEnabled);
    data[@"os_version"] = pi.operatingSystemVersionString;
    data[@"uptime_seconds"] = @(pi.systemUptime);
    data[@"battery"] = get_battery_data();
    data[@"storage"] = get_storage_data();

    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"info", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_battery(int stdout_fd, BOOL compact, BOOL quiet) {
    NSDictionary *data = get_battery_data();
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"battery", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int cmd_storage(int stdout_fd, BOOL compact, BOOL quiet) {
    NSDictionary *data = get_storage_data();
    noff_emit_json(stdout_fd, noff_json_envelope(TOOL_NAME, @"storage", data), compact, quiet);
    return NOFF_EXIT_SUCCESS;
}

static int device_handler(int argc, char **argv,
                           int stdin_fd, int stdout_fd, int stderr_fd) {
    if (noff_has_flag(argc, argv, "--help") || noff_has_flag(argc, argv, "-h")) {
        noff_emit_help(stderr_fd, HELP_TEXT);
        return NOFF_EXIT_SUCCESS;
    }

    BOOL compact = noff_has_flag(argc, argv, "--compact");
    BOOL quiet = noff_has_flag(argc, argv, "-q") || noff_has_flag(argc, argv, "--quiet");

    NSString *subcmd = noff_get_subcommand(argc, argv);
    if (!subcmd) {
        // [T-offload-defaults-batch-ios] Bare `apple-device` (including
        // flags-only invocations) defaults to `info` — the full-info dump is
        // the obvious "tell me about this device" intent. (Android's
        // android-device defaults to its `all` verb; the verbs differ per
        // platform but the bare-invocation behavior now matches.)
        subcmd = @"info";
    }

    if ([subcmd isEqualToString:@"info"]) {
        return cmd_info(stdout_fd, compact, quiet);
    } else if ([subcmd isEqualToString:@"battery"]) {
        return cmd_battery(stdout_fd, compact, quiet);
    } else if ([subcmd isEqualToString:@"storage"]) {
        return cmd_storage(stdout_fd, compact, quiet);
    }

    noff_emit_help(stderr_fd, HELP_TEXT);
    NSDictionary *err = noff_json_error(TOOL_NAME, subcmd,
                                         NOFF_ERR_INVALID_ARGS,
                                         [NSString stringWithFormat:@"Unknown command '%@'. Valid commands: info, battery, storage. Use --help for details.", subcmd]);
    noff_emit_json(stdout_fd, err, compact, quiet);
    return NOFF_EXIT_INVALID_ARGS;
}

void device_offload_register(void) {
    int err = native_offload_add_handler("apple-device", device_handler);
    if (err == 0) {
        noff_ensure_guest_stub("/usr/local/bin/apple-device");
        NSLog(@"NativeOffloads: apple-device handler registered");
    } else {
        NSLog(@"NativeOffloads: failed to register apple-device handler (err=%d)", err);
    }
}
