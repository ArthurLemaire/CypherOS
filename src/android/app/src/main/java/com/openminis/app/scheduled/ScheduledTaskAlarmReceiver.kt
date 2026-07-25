package com.openminis.app.scheduled

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.openminis.app.logging.AppLogger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * [T-android-scheduled-tasks-design] Receives an AlarmManager fire and
 * hands the task off to [ScheduledAgentRunner]. Uses goAsync() because
 * the agent loop is long-running (well past the 10s BroadcastReceiver
 * budget) — the [ScheduledAgentRunner] starts the foreground service
 * which keeps the process alive while the agent runs.
 */
class ScheduledTaskAlarmReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ScheduledTaskManager.ACTION_FIRE) return
        val taskId = intent.getStringExtra(ScheduledTaskManager.EXTRA_TASK_ID) ?: return

        AppLogger.info(TAG, "fire received: task=$taskId")

        val pending = goAsync()
        val appContext = context.applicationContext
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        scope.launch {
            try {
                val manager = ScheduledTaskManager(appContext)
                val task = manager.get(taskId) ?: run {
                    AppLogger.warning(TAG, "task $taskId not found in store — skipping")
                    return@launch
                }
                if (!task.enabled) {
                    AppLogger.info(TAG, "task $taskId disabled — skipping fire")
                    return@launch
                }
                // Schedule the next occurrence FIRST so a long-running
                // prompt doesn't block tomorrow's fire even if we crash.
                manager.rescheduleNext(taskId)

                ScheduledAgentRunner.run(appContext, task)
            } catch (t: Throwable) {
                AppLogger.error(TAG, "task $taskId fire failed: ${t.message}")
            } finally {
                pending.finish()
            }
        }
    }

    companion object {
        private const val TAG = "ScheduledTaskRecv"
    }
}
