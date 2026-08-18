// T283 — native crash → file (NDK signal handler).
//
// Registered at app startup from MinisApp.onCreate via JNI. Catches
// fatal signals raised inside JNI / proot / pty_bridge / any other
// native code, writes a one-shot text report to the configured logs
// dir, then restores the default handler and re-raises so the system
// tombstone is also generated and the app exits like normal.
//
// Strict async-signal-safety: only signal-safe libc calls inside the
// handler (open/write/close/snprintf are safe; printf/malloc are not).

#include <jni.h>
#include <signal.h>
#include <unistd.h>
#include <fcntl.h>
#include <cstring>
#include <cstdio>
#include <ctime>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <android/log.h>

#define LOG_TAG "MinisCrashHandler"

// Plenty of headroom for "<logs_dir>/native-crash-YYYY-MM-DD_HH-MM-SS.log".
static char g_log_dir[512] = {0};

// Reentrancy guard. If the handler crashes itself, we want the second
// signal to skip straight to SIG_DFL rather than recursing.
static volatile sig_atomic_t g_in_handler = 0;

// Signal name lookup — strsignal() is NOT async-signal-safe on all
// libc implementations, so use a hardcoded table.
static const char* signal_name(int sig) {
    switch (sig) {
        case SIGSEGV: return "SIGSEGV";
        case SIGABRT: return "SIGABRT";
        case SIGBUS:  return "SIGBUS";
        case SIGFPE:  return "SIGFPE";
        case SIGILL:  return "SIGILL";
        case SIGSYS:  return "SIGSYS";
        case SIGTRAP: return "SIGTRAP";
        default:      return "UNKNOWN";
    }
}

static void crash_signal_handler(int sig, siginfo_t* info, void* ctx) {
    // Reentrancy: if we're already in the handler, just restore default
    // and re-raise. Avoids infinite loop when the handler itself faults.
    if (g_in_handler) {
        signal(sig, SIG_DFL);
        raise(sig);
        return;
    }
    g_in_handler = 1;

    if (g_log_dir[0] == 0) {
        signal(sig, SIG_DFL);
        raise(sig);
        return;
    }

    // Build the per-crash filename. time(NULL) is async-signal-safe;
    // localtime_r is too on bionic. snprintf is documented async-safe
    // by POSIX.
    time_t now = time(nullptr);
    struct tm tm_buf;
    localtime_r(&now, &tm_buf);

    char path[640];
    snprintf(path, sizeof(path),
        "%s/native-crash-%04d-%02d-%02d_%02d-%02d-%02d.log",
        g_log_dir,
        tm_buf.tm_year + 1900, tm_buf.tm_mon + 1, tm_buf.tm_mday,
        tm_buf.tm_hour, tm_buf.tm_min, tm_buf.tm_sec);

    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        signal(sig, SIG_DFL);
        raise(sig);
        return;
    }

    // Thread name — the single most useful missing field. /proc/self/comm is a
    // 16-byte name that immediately says WHICH subsystem died (e.g. "Jit thread
    // pool", "native-offload-", "RenderThread"), which the previous report,
    // carrying only a numeric tid, could never answer after the fact.
    char comm[64] = {0};
    {
        int cfd = open("/proc/self/comm", O_RDONLY);
        if (cfd >= 0) {
            ssize_t r = read(cfd, comm, sizeof(comm) - 1);
            if (r > 0) {
                comm[r] = 0;
                for (ssize_t i = 0; i < r; i++) if (comm[i] == '\n') comm[i] = 0;
            }
            close(cfd);
        }
    }
    if (comm[0] == 0) strncpy(comm, "(unknown)", sizeof(comm) - 1);

    const int tid = (int)syscall(SYS_gettid);
    const int code = info ? info->si_code : 0;

    // si_addr is ONLY a fault address for fault-type si_codes. For SI_USER(0) /
    // SI_QUEUE(-1) / SI_TKILL(-6) the kernel fills the _kill{pid,uid} arm of the
    // SAME siginfo union, so reading si_addr yields (uid << 32) | pid — a
    // meaningless "address" that reads like a wild pointer and sends triage
    // chasing a memory bug that does not exist. Report the union honestly.
    //
    // Measured on arm64/Android 13: abort() -> si_code=-1 with si_addr
    // 0x<uid><pid>; raise() -> -6; kill() -> 0; a genuine SIGSEGV -> si_code 1/2
    // with a real address.
    const bool addr_is_fault = !(code == 0 || code == -1 || code == -6);

    char buf[1600];
    int n;
    if (addr_is_fault) {
        n = snprintf(buf, sizeof(buf),
            "=== Minis Native Crash ===\n"
            "Time: %04d-%02d-%02d %02d:%02d:%02d\n"
            "Signal: %d (%s)\n"
            "si_code: %d\n"
            "Fault addr: %p\n"
            "PID: %d  TID: %d  Thread: %s\n"
            "\n"
            "(Tombstone with full backtrace written by Android system to "
            "/data/tombstones/ — adb pull or `adb bugreport`.)\n",
            tm_buf.tm_year + 1900, tm_buf.tm_mon + 1, tm_buf.tm_mday,
            tm_buf.tm_hour, tm_buf.tm_min, tm_buf.tm_sec,
            sig, signal_name(sig), code,
            info ? info->si_addr : nullptr,
            getpid(), tid, comm);
    } else {
        n = snprintf(buf, sizeof(buf),
            "=== Minis Native Crash ===\n"
            "Time: %04d-%02d-%02d %02d:%02d:%02d\n"
            "Signal: %d (%s)\n"
            "si_code: %d (%s)\n"
            "Sent by: pid=%d uid=%d%s\n"
            "Fault addr: n/a (not a fault signal — see note)\n"
            "PID: %d  TID: %d  Thread: %s\n"
            "\n"
            "NOTE: this signal was SENT, not raised by a memory fault, so\n"
            "si_addr carries no address. SIGABRT with si_code=-1 and\n"
            "sender pid == our own pid is the ordinary signature of abort()\n"
            "inside this process (libc assertion, Scudo heap check, ART\n"
            "runtime abort, or a C++ uncaught exception).\n"
            "The REASON is not in siginfo — look for the abort message:\n"
            "  * logcat around this timestamp, tags: scudo / libc / DEBUG\n"
            "    (Scudo prints e.g. \"Scudo ERROR: invalid chunk state\")\n"
            "  * the tombstone's \"Abort message:\" line\n"
            "(Tombstone with full backtrace written by Android system to "
            "/data/tombstones/ — adb pull or `adb bugreport`.)\n",
            tm_buf.tm_year + 1900, tm_buf.tm_mon + 1, tm_buf.tm_mday,
            tm_buf.tm_hour, tm_buf.tm_min, tm_buf.tm_sec,
            sig, signal_name(sig),
            code,
            code == 0 ? "SI_USER" : (code == -1 ? "SI_QUEUE/abort()" : "SI_TKILL"),
            info ? info->si_pid : 0, info ? (int)info->si_uid : 0,
            (info && info->si_pid == getpid()) ? " (this process — self-abort)" : "",
            getpid(), tid, comm);
    }
    if (n > 0) {
        ssize_t written = 0;
        while (written < n) {
            ssize_t w = write(fd, buf + written, n - written);
            if (w <= 0) break;
            written += w;
        }
    }
    close(fd);

    // Re-raise with default handler so Android still produces a tombstone
    // and ActivityManager handles process-death the normal way.
    struct sigaction sa{};
    sa.sa_handler = SIG_DFL;
    sigemptyset(&sa.sa_mask);
    sigaction(sig, &sa, nullptr);
    raise(sig);
}

extern "C" JNIEXPORT void JNICALL
Java_com_openminis_app_crash_NativeCrashHandler_nativeInstall(
        JNIEnv* env, jobject /*thiz*/, jstring jLogDir) {
    if (jLogDir == nullptr) return;
    const char* dir = env->GetStringUTFChars(jLogDir, nullptr);
    if (dir == nullptr) return;
    strncpy(g_log_dir, dir, sizeof(g_log_dir) - 1);
    g_log_dir[sizeof(g_log_dir) - 1] = 0;
    env->ReleaseStringUTFChars(jLogDir, dir);

    // mkdir is fine here — we're on the JVM thread, not in a signal.
    mkdir(g_log_dir, 0755);

    struct sigaction sa{};
    sa.sa_sigaction = crash_signal_handler;
    sa.sa_flags = SA_SIGINFO;
    sigemptyset(&sa.sa_mask);

    // Register for the signals that map to JNI/native bugs we actually
    // want to capture. SIGABRT covers __android_log_assert / abort()
    // from libc; SIGSEGV/BUS/ILL cover most JNI memory bugs; SIGFPE
    // covers integer div-by-zero. SIGSYS catches seccomp violations
    // (proot occasionally trips these on new kernels).
    sigaction(SIGSEGV, &sa, nullptr);
    sigaction(SIGABRT, &sa, nullptr);
    sigaction(SIGBUS,  &sa, nullptr);
    sigaction(SIGFPE,  &sa, nullptr);
    sigaction(SIGILL,  &sa, nullptr);
    sigaction(SIGSYS,  &sa, nullptr);

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
        "installed: dir=%s", g_log_dir);
}
