package io.github.nanomuse.guard

import android.content.Context
import com.openminis.app.R

/** The words on the card and the notification, in the user's language. */
object RiskText {
    fun targetLabel(context: Context, target: String?): String? = when (target) {
        null -> null
        ShellGuard.WORKSPACE -> context.getString(R.string.nm_risk_target_workspace)
        ShellGuard.SHARED -> context.getString(R.string.nm_risk_target_shared)
        else -> target.removePrefix("lark:").removePrefix("git:")
    }

    fun title(context: Context, request: RiskRequest, agentName: String): String {
        val a = request.assessment
        val target = targetLabel(context, a.target)
        if (a.warnings.isNotEmpty()) return context.getString(R.string.nm_risk_title_warning, agentName)
        return when (a.riskClass) {
            RiskClass.DESTRUCTIVE -> if (target != null) context.getString(R.string.nm_risk_title_destructive, agentName, target)
            else context.getString(R.string.nm_risk_title_destructive_generic, agentName)
            RiskClass.MONEY -> if (target != null) context.getString(R.string.nm_risk_title_money, agentName, target)
            else context.getString(R.string.nm_risk_title_money_generic, agentName)
            else -> if (target != null) context.getString(R.string.nm_risk_title_outbound, agentName, target)
            else context.getString(R.string.nm_risk_title_outbound_generic, agentName)
        }
    }

    fun description(context: Context, request: RiskRequest, agentName: String): String {
        val a = request.assessment
        if (a.warnings.isNotEmpty()) {
            return context.getString(R.string.nm_risk_desc_warning, a.warnings.joinToString(", ") { warningLabel(context, it) })
        }
        if (request.kind == GuardKind.BROWSER) {
            val host = a.target ?: request.pageUrl ?: ""
            return context.getString(R.string.nm_risk_desc_browser, agentName, request.elementText ?: "", host)
        }
        if (request.kind == GuardKind.SCREEN) {
            val app = request.pageUrl ?: a.target ?: context.getString(R.string.nm_hands_this_phone)
            return context.getString(R.string.nm_risk_desc_screen, agentName, request.elementText ?: "", app)
        }
        val target = targetLabel(context, a.target)
        return when (a.riskClass) {
            RiskClass.DESTRUCTIVE -> if (target != null) context.getString(R.string.nm_risk_desc_shell_destructive, agentName, target)
            else context.getString(R.string.nm_risk_desc_shell_destructive_generic, agentName)
            RiskClass.MONEY -> if (target != null) context.getString(R.string.nm_risk_desc_shell_money, agentName, target)
            else context.getString(R.string.nm_risk_desc_shell_money_generic, agentName)
            else -> if (target != null) context.getString(R.string.nm_risk_desc_shell_outbound, agentName, target)
            else context.getString(R.string.nm_risk_desc_shell_outbound_generic, agentName)
        }
    }

    fun classLabel(context: Context, riskClass: RiskClass): String = when (riskClass) {
        RiskClass.DESTRUCTIVE -> context.getString(R.string.nm_risk_class_destructive)
        RiskClass.OUTBOUND -> context.getString(R.string.nm_risk_class_outbound)
        RiskClass.MONEY -> context.getString(R.string.nm_risk_class_money)
        RiskClass.INSTALL -> context.getString(R.string.nm_risk_class_install)
        RiskClass.SAFE -> ""
    }

    private fun warningLabel(context: Context, warning: String): String = when {
        warning.startsWith("wipes ") -> context.getString(R.string.nm_risk_warn_wipes, warning.removePrefix("wipes "))
        warning == "disk-level operation" -> context.getString(R.string.nm_risk_warn_disk)
        warning == "writes to a block device" -> context.getString(R.string.nm_risk_warn_disk)
        warning == "system-level command" -> context.getString(R.string.nm_risk_warn_system)
        warning == "world-writable permissions" -> context.getString(R.string.nm_risk_warn_perms)
        warning == "force push" -> context.getString(R.string.nm_risk_warn_force_push)
        warning == "fork bomb" -> context.getString(R.string.nm_risk_warn_fork_bomb)
        warning.startsWith("pipes a download") -> context.getString(R.string.nm_risk_warn_pipe_sh)
        else -> warning
    }
}
