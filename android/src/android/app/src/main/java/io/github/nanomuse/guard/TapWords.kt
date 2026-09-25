package io.github.nanomuse.guard

/**
 * What a button's label says it does. Shared by the browser (the element's text) and the
 * phone screen (the label the screen model reports for the tap), so the same words stop for
 * the same approval on every rung of the ladder.
 */
object TapWords {
    val secretField = Regex(
        "passw|pwd|密码|口令|verif|otp|一次性|验证码|校验码|动态码|短信码|sms.?code|auth.?code|security.?code|\\bpin\\b|captcha|图形码|cvv|cvc|安全码",
        RegexOption.IGNORE_CASE,
    )
    private val moneyTap = Regex(
        "支付|付款|立即购买|确认购买|去支付|确认支付|结算|下单|提交订单|立即下单|买单|充值|转账|打赏|购买|订阅|开通|续费|确认付款|立即支付|\\bpay\\b|pay now|payment|checkout|place order|buy now|purchase|(?<!un)subscribe|donate|transfer|top ?up|confirm order|complete order|confirm purchase|book now|reserve",
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

    /** The class a tap on [label] falls in, or null when it is an ordinary tap. */
    fun classify(label: String): RiskClass? = when {
        label.isBlank() -> null
        moneyTap.containsMatchIn(label) -> RiskClass.MONEY
        destructiveTap.containsMatchIn(label) -> RiskClass.DESTRUCTIVE
        outboundTap.containsMatchIn(label) -> RiskClass.OUTBOUND
        else -> null
    }

    /** The reason line for the card, from the class and the label. */
    fun reason(cls: RiskClass, short: String, where: String?): String = when (cls) {
        RiskClass.MONEY -> "taps “$short” — looks like a payment"
        RiskClass.DESTRUCTIVE -> "taps “$short” — looks like it deletes something"
        else -> "taps “$short” — looks like it sends or posts"
    } + (where?.let { " on $it" } ?: "")

    fun looksSecret(text: String): Boolean = secretField.containsMatchIn(text)
}
