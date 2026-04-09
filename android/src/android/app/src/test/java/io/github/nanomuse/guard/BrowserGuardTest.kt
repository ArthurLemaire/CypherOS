package io.github.nanomuse.guard

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BrowserGuardTest {
    private fun target(
        type: String = "", name: String = "", id: String = "", placeholder: String = "", autocomplete: String = "",
        inputMode: String = "", aria: String = "", label: String = "", text: String = "", maxLength: Int = 0,
        host: String = "shop.example.com",
    ) = BrowserGuard.Target(true, "INPUT", type, name, id, placeholder, autocomplete, inputMode, aria, label, text, "", maxLength, "https://$host/x", host)

    @Test fun `password and code fields are refused`() {
        assertTrue(BrowserGuard.judgeType(target(type = "password")) is BrowserGuard.Verdict.Refuse)
        assertTrue(BrowserGuard.judgeType(target(autocomplete = "one-time-code")) is BrowserGuard.Verdict.Refuse)
        assertTrue(BrowserGuard.judgeType(target(placeholder = "请输入验证码")) is BrowserGuard.Verdict.Refuse)
        assertTrue(BrowserGuard.judgeType(target(label = "SMS code", inputMode = "numeric", maxLength = 6)) is BrowserGuard.Verdict.Refuse)
        assertTrue(BrowserGuard.judgeType(target(name = "user_pwd")) is BrowserGuard.Verdict.Refuse)
        val r = BrowserGuard.judgeType(target(type = "password")) as BrowserGuard.Verdict.Refuse
        assertTrue(r.text.startsWith(BrowserGuard.HANDOFF_PREFIX))
    }

    @Test fun `ordinary fields are typed into`() {
        assertTrue(BrowserGuard.judgeType(target(type = "text", name = "q", placeholder = "Search")) is BrowserGuard.Verdict.Proceed)
        assertTrue(BrowserGuard.judgeType(target(type = "email", name = "email")) is BrowserGuard.Verdict.Proceed)
        assertTrue(BrowserGuard.judgeType(target(type = "text", name = "pinyin")) is BrowserGuard.Verdict.Proceed)
        assertTrue(BrowserGuard.judgeType(target(type = "text", label = "邮编", inputMode = "numeric", maxLength = 6)) is BrowserGuard.Verdict.Proceed)
    }

    @Test fun `pay send delete taps ask with the host as target`() {
        val pay = BrowserGuard.judgeClick(target(text = "确认支付 ¥38.00")) as BrowserGuard.Verdict.Ask
        assertEquals(RiskClass.MONEY, pay.assessment.riskClass)
        assertEquals("shop.example.com", pay.assessment.target)
        val send = BrowserGuard.judgeClick(target(text = "发送", host = "mail.example.com")) as BrowserGuard.Verdict.Ask
        assertEquals(RiskClass.OUTBOUND, send.assessment.riskClass)
        val del = BrowserGuard.judgeClick(target(aria = "Delete conversation")) as BrowserGuard.Verdict.Ask
        assertEquals(RiskClass.DESTRUCTIVE, del.assessment.riskClass)
        val order = BrowserGuard.judgeClick(target(text = "Place order")) as BrowserGuard.Verdict.Ask
        assertEquals(RiskClass.MONEY, order.assessment.riskClass)
    }

    @Test fun `navigation taps proceed`() {
        for (t in listOf("下一页", "查看详情", "Search", "Log in", "Add to cart", "Open menu", "商品详情", "筛选"))
            assertTrue(t, BrowserGuard.judgeClick(target(text = t)) is BrowserGuard.Verdict.Proceed)
    }

    @Test fun `describe js embeds the selector safely`() {
        val js = BrowserGuard.describeJs("button[name=\"pay\"]", null, null)
        assertTrue(js.contains("document.querySelector(\"button[name=\\\"pay\\\"]\")"))
        assertTrue(BrowserGuard.describeJs(null, 10, 20).contains("elementFromPoint(10, 20)"))
    }
}
