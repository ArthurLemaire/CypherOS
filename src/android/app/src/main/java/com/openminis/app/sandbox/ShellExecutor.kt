package com.openminis.app.sandbox

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.io.BufferedReader
import java.io.InputStreamReader
import java.nio.charset.StandardCharsets

/**
 * Executes shell commands inside the PRoot sandbox via ProcessBuilder.
 * Corresponds to iOS ISHShellExecutor.
 */
object ShellExecutor {

    private const val TAG = "ShellExecutor"
    private const val DEFAULT_TIMEOUT_MS = 600_000L // 10 minutes

    data class ShellResult(
        val output: String,
        val exitCode: Int,
        val durationMs: Long
    )

    /** The currently running process, if any. Can be destroyed to stop execution. */
    @Volatile
    var currentProcess: Process? = null
        private set

    /**
     * Execute a command inside the PRoot sandbox.
     *
     * @param context Android context for resolving PROOT_TMP_DIR
     * @param command Shell command string to execute
     * @param timeout Timeout in milliseconds (default 10 minutes)
     * @param environment Additional environment variables
     * @param lineCallback Called for each line of output (on IO dispatcher)
     * @return ShellResult with combined stdout+stderr, exit code, and duration
     */
    suspend fun execute(
        context: Context,
        command: String,
        timeout: Long = DEFAULT_TIMEOUT_MS,
        environment: Map<String, String> = emptyMap(),
        lineCallback: ((String) -> Unit)? = null
    ): ShellResult = withContext(Dispatchers.IO) {
        check(PRootKernel.isBooted) { "PRootKernel must be booted before executing commands" }

        val prootCommand = PRootKernel.buildProotCommand(command)

        Log.d(TAG, "Executing: $command")

        val startTime = System.currentTimeMillis()

        val processBuilder = ProcessBuilder(prootCommand)
        processBuilder.redirectErrorStream(true)

        // Set required environment for PRoot
        val env = processBuilder.environment()
        env["PROOT_TMP_DIR"] = PRootKernel.getProotTmpDir(context).absolutePath
        if (PRootKernel.nativeLibDir.isNotEmpty()) {
            env["LD_LIBRARY_PATH"] = PRootKernel.nativeLibDir
        }
        if (PRootKernel.prootLoaderPath.isNotEmpty()) {
            env["PROOT_LOADER"] = PRootKernel.prootLoaderPath
        }
        if (PRootKernel.prootLoader32Path.isNotEmpty()) {
            env["PROOT_LOADER_32"] = PRootKernel.prootLoader32Path
        }

        // Apply custom environment from PRootKernel
        for ((key, value) in PRootKernel.customEnvironment) {
            env[key] = value
        }

        // Apply per-call environment overrides
        for ((key, value) in environment) {
            env[key] = value
        }

        val output = StringBuilder()
        var exitCode = -1

        try {
            withTimeout(timeout) {
                val process = processBuilder.start()
                currentProcess = process

                try {
                    // Read raw chars to preserve \r for TerminalSanitizer CR-folding.
                    // readLine() would consume \r as line terminator, losing progress overwrites.
                    InputStreamReader(process.inputStream, StandardCharsets.UTF_8).use { reader ->
                        val buf = CharArray(4096)
                        var lastLineForCallback = StringBuilder()
                        var n: Int
                        while (reader.read(buf).also { n = it } != -1) {
                            output.append(buf, 0, n)
                            // Feed lines to callback for UI updates
                            if (lineCallback != null) {
                                for (i in 0 until n) {
                                    val c = buf[i]
                                    if (c == '\n') {
                                        lineCallback.invoke(lastLineForCallback.toString())
                                        lastLineForCallback.clear()
                                    } else if (c != '\r') {
                                        lastLineForCallback.append(c)
                                    }
                                }
                            }
                        }
                        if (lineCallback != null && lastLineForCallback.isNotEmpty()) {
                            lineCallback.invoke(lastLineForCallback.toString())
                        }
                    }

                    exitCode = process.waitFor()
                } finally {
                    currentProcess = null
                }
            }
        } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
            Log.w(TAG, "Command timed out after ${timeout}ms: $command")
            currentProcess?.destroyForcibly()
            currentProcess = null
            output.appendLine("\n[Command timed out after ${timeout / 1000}s]")
            exitCode = 124 // Standard timeout exit code
        } catch (e: Exception) {
            Log.e(TAG, "Command failed: $command", e)
            currentProcess?.destroyForcibly()
            currentProcess = null
            output.appendLine("\n[Error: ${e.message}]")
            exitCode = -1
        }

        val durationMs = System.currentTimeMillis() - startTime
        Log.d(TAG, "Command completed in ${durationMs}ms with exit code $exitCode")

        ShellResult(
            output = output.toString().trimEnd(),
            exitCode = exitCode,
            durationMs = durationMs
        )
    }

    /**
     * Forcibly destroy the currently running process.
     */
    fun destroyCurrent() {
        currentProcess?.let { process ->
            Log.i(TAG, "Destroying current process")
            process.destroyForcibly()
            currentProcess = null
        }
    }
}
