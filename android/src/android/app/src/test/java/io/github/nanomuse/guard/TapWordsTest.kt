package io.github.nanomuse.guard

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TapWordsTest {

    @Test fun `paying words are money`() {
        for (label in listOf("立即购买", "去支付", "提交订单", "Pay now", "Place order", "Checkout", "充值", "订阅", "Book now")) {
            assertEquals(label, RiskClass.MONEY, TapWords.classify(label))
        }
    }

    @Test fun `deleting words are destructive`() {
        for (label in listOf("删除", "清空", "取消订单", "Delete", "Remove", "Unsubscribe", "退款")) {
            assertEquals(label, RiskClass.DESTRUCTIVE, TapWords.classify(label))
        }
    }

    @Test fun `sending words are outbound`() {
        for (label in listOf("发送", "发布", "Send", "Post", "Reply", "评论", "提交")) {
            assertEquals(label, RiskClass.OUTBOUND, TapWords.classify(label))
        }
    }

    @Test fun `ordinary taps pass`() {
        for (label in listOf("", "搜索", "查询", "北京南", "Next", "OK", "详情", "08:00 G1234", "筛选")) {
            assertNull(label, TapWords.classify(label))
        }
    }

    @Test fun `money outranks the rest`() {
        assertEquals(RiskClass.MONEY, TapWords.classify("提交订单并支付"))
        assertEquals(RiskClass.MONEY, TapWords.classify("Delete and pay"))
    }

    @Test fun `secret fields are recognised`() {
        for (f in listOf("密码", "Password", "验证码", "SMS code", "OTP", "PIN", "captcha", "CVV", "安全码", "口令")) {
            assertTrue(f, TapWords.looksSecret(f))
        }
        for (f in listOf("search", "出发地", "收货人", "备注", "pinyin", "邮编")) {
            assertFalse(f, TapWords.looksSecret(f))
        }
    }

    @Test fun `the reason names the label and the place`() {
        assertEquals("taps “去支付” — looks like a payment on 铁路12306", TapWords.reason(RiskClass.MONEY, "去支付", "铁路12306"))
        assertEquals("taps “删除” — looks like it deletes something", TapWords.reason(RiskClass.DESTRUCTIVE, "删除", null))
        assertEquals("taps “Send” — looks like it sends or posts on mail.example", TapWords.reason(RiskClass.OUTBOUND, "Send", "mail.example"))
    }
}
