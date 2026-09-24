package io.github.nanomuse.guard

import com.openminis.app.logging.AppLogger
import org.json.JSONObject

/**
 * Looks at what a `browser_use` click or type is about to touch, before it happens.
 *
 * Two rules, both Muse's: the agent never types into a password or verification-code field
 * (it hands the in-app browser to the user instead), and a tap whose label says pay, send or
 * delete goes through the approval card first, bound to the page's host.
 */
object BrowserGuard {
    private const val TAG = "nanoMuse.BrowserGuard"

    /** Prefix on a refusal so the chat layer knows to bring the browser sheet forward. */
    const val HANDOFF_PREFIX = "[nanoMuse handoff]"

    sealed class Verdict {
        object Proceed : Verdict()
        /** Refused outright (secret field). [text] is what the model reads. */
        data class Refuse(val text: String) : Verdict()
        /** Needs the user's yes first. */
        data class Ask(val assessment: RiskAssessment, val elementText: String) : Verdict()
    }

    /** Everything we look at, gathered in one `evaluateJavascript`. */
    data class Target(
        val found: Boolean,
        val tag: String,
        val type: String,
        val name: String,
        val id: String,
        val placeholder: String,
        val autocomplete: String,
        val inputMode: String,
        val aria: String,
        val label: String,
        val text: String,
        val href: String,
        val maxLength: Int,
        val url: String,
        val host: String,
    ) {
        companion object {
            fun parse(json: String): Target? = runCatching {
                val o = JSONObject(json)
                Target(
                    found = o.optBoolean("found", false),
                    tag = o.optString("tag"), type = o.optString("type"), name = o.optString("name"),
                    id = o.optString("id"), placeholder = o.optString("placeholder"),
                    autocomplete = o.optString("autocomplete"), inputMode = o.optString("inputmode"),
                    aria = o.optString("aria"), label = o.optString("label"), text = o.optString("text"),
                    href = o.optString("href"), maxLength = o.optString("maxlength").toIntOrNull() ?: 0,
                    url = o.optString("url"), host = o.optString("host"),
                )
            }.getOrNull()
        }
    }

    private val secretField = Regex(
        "passw|pwd|密码|口令|verif|otp|一次性|验证码|校验码|动态码|短信码|sms.?code|auth.?code|security.?code|\\bpin\\b|captcha|图形码|cvv|cvc|安全码",
        RegexOption.IGNORE_CASE,
    )
    private val moneyTap = Regex(
        "支付|付款|立即购买|确认购买|去支付|确认支付|结算|下单|提交订单|立即下单|买单|充值|转账|打赏|购买|订阅|开通|续费|确认付款|立即支付|\\bpay\\b|pay now|payment|checkout|place order|buy now|purchase|subscribe|donate|transfer|top ?up|confirm order|complete order|confirm purchase|book now|reserve",
        RegexOption.IGNORE_CASE,
    )
    private val destructiveTap = Regex(
        "删除|移除|清空|注销|解绑|退订|取消订单|退款|\\bdelete\\b|\\bremove\\b|clear all|unsubscribe|deactivate|cancel order|\\brefund\\b|\\bdiscard\\b|\\berase\\b",
        RegexOption.IGNORE_CASE,
    )
    private val outboundTap = Regex(
        "^发送$|发送|发布|回复|投递|转发|评论|发表|发帖|提交|确认发送|\\bsend\\b|\\bpost\\b|\\bpublish\\b|\\breply\\b|\\bshare\\b|\\btweet\\b|\\bcomment\\b|\\bsubmit\\b|\\bapply\\b",
        RegexOption.IGNORE_CASE,
    )

    /** The JS that describes the element a click/type will land on. Returns a JSON object. */
    fun describeJs(selector: String?, x: Int?, y: Int?): String {
        val pick = when {
            selector != null -> "document.querySelector(${JSONObject.quote(selector)})"
            x != null && y != null -> "document.elementFromPoint($x, $y)"
            else -> "null"
        }
        return """
            (function(){
              var el = null; try { el = $pick; } catch (e) {}
              if (!el) return JSON.stringify({found:false, url: location.href, host: location.host});
              function s(v){ return ((v == null ? '' : v) + '').replace(/\s+/g,' ').trim().slice(0, 160); }
              var inp = el.closest ? (el.closest('input,textarea,select,[contenteditable=true],[contenteditable=""]') || el) : el;
              var btn = el.closest ? (el.closest('button,a,[role=button],[role=link],input[type=submit],input[type=button],input[type=image],[onclick],summary,label') || el) : el;
              var lbl = '';
              try { if (inp.labels && inp.labels[0]) lbl = inp.labels[0].innerText; else if (inp.id) { var l = document.querySelector('label[for="' + inp.id + '"]'); if (l) lbl = l.innerText; } } catch (e) {}
              var txt = btn.innerText || btn.value || btn.getAttribute('aria-label') || btn.getAttribute('title') || btn.getAttribute('alt') || '';
              if (!s(txt) && btn.querySelector) { var im = btn.querySelector('img[alt]'); if (im) txt = im.getAttribute('alt'); }
              return JSON.stringify({
                found: true, tag: el.tagName, type: s(inp.getAttribute && inp.getAttribute('type')).toLowerCase(),
                name: s(inp.getAttribute && inp.getAttribute('name')), id: s(inp.id), placeholder: s(inp.getAttribute && inp.getAttribute('placeholder')),
                autocomplete: s(inp.getAttribute && inp.getAttribute('autocomplete')).toLowerCase(), inputmode: s(inp.getAttribute && inp.getAttribute('inputmode')).toLowerCase(),
                aria: s(inp.getAttribute && inp.getAttribute('aria-label')), label: s(lbl), text: s(txt),
                href: s(btn.getAttribute && btn.getAttribute('href')), maxlength: s(inp.getAttribute && inp.getAttribute('maxlength')),
                url: location.href, host: location.host
              });
            })()
        """.trimIndent()
    }

    fun judgeType(t: Target): Verdict {
        if (!t.found) return Verdict.Proceed
        val looksSecret = t.type == "password" ||
            t.autocomplete in setOf("one-time-code", "current-password", "new-password", "cc-csc") ||
            listOf(t.name, t.id, t.placeholder, t.aria, t.label).any { secretField.containsMatchIn(it) } ||
            (t.inputMode == "numeric" && t.maxLength in 4..8 && listOf(t.placeholder, t.aria, t.label).any { Regex("code|码", RegexOption.IGNORE_CASE).containsMatchIn(it) })
        if (!looksSecret) return Verdict.Proceed
        AppLogger.info(TAG, "refused typing into a secret field on ${t.host}")
        return Verdict.Refuse(
            "$HANDOFF_PREFIX Refused: that field looks like a password or verification code, and the agent never types " +
                "those. The in-app browser has been brought to the front — ask the user to enter it there themselves and " +
                "tell you when it is done, then continue from the page as it is. Do not try another selector or JavaScript for this field.",
        )
    }

    fun judgeClick(t: Target): Verdict {
        if (!t.found) return Verdict.Proceed
        val label = listOf(t.text, t.aria).firstOrNull { it.isNotBlank() } ?: return Verdict.Proceed
        val host = t.host.ifBlank { null }
        val cls = when {
            moneyTap.containsMatchIn(label) -> RiskClass.MONEY
            destructiveTap.containsMatchIn(label) -> RiskClass.DESTRUCTIVE
            outboundTap.containsMatchIn(label) -> RiskClass.OUTBOUND
            else -> return Verdict.Proceed
        }
        val short = label.take(40)
        val reason = when (cls) {
            RiskClass.MONEY -> "taps “$short” — looks like a payment"
            RiskClass.DESTRUCTIVE -> "taps “$short” — looks like it deletes something"
            else -> "taps “$short” — looks like it sends or posts"
        } + (host?.let { " on $it" } ?: "")
        return Verdict.Ask(RiskAssessment(cls, reason, host), short)
    }
}
