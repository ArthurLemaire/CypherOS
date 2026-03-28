package io.github.nanomuse.hands

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class HandsActionTest {

    @Test fun `thought and click are read`() {
        val p = HandsAction.parse(
            """
            Thought: The search box is at the top; I tap it.
            Action: {"action_type": "click", "coordinate": [500, 120], "target": "搜索"}
            """.trimIndent(),
        )
        assertEquals("The search box is at the top; I tap it.", p.thought)
        val a = p.action as HandsAction.Click
        assertEquals(HandsAction.Point(500, 120), a.at)
        assertEquals("搜索", a.target)
        assertEquals("搜索", a.tapTarget)
    }

    @Test fun `grid maps to pixels`() {
        assertEquals(540 to 240, HandsAction.Point(500, 100).toPixels(1080, 2400))
        assertEquals(0 to 0, HandsAction.Point(0, 0).toPixels(1080, 2400))
        assertEquals(1079 to 2398, HandsAction.Point(999, 999).toPixels(1080, 2400))
        // Never off the screen, whatever the grid says.
        assertEquals(99 to 99, HandsAction.Point(999, 999).toPixels(100, 100))
    }

    @Test fun `fractions and pixels-of-a-1000-image both land on the grid`() {
        val frac = HandsAction.fromJson(JSONObject("""{"action_type":"click","coordinate":[0.5,0.25]}""")) as HandsAction.Click
        assertEquals(HandsAction.Point(500, 250), frac.at)
        val big = HandsAction.fromJson(JSONObject("""{"action_type":"click","coordinate":[1200,-5]}""")) as HandsAction.Click
        assertEquals(HandsAction.Point(999, 0), big.at)
    }

    @Test fun `fenced json, missing thought label and trailing text are tolerated`() {
        val p = HandsAction.parse(
            "I should scroll.\nAction:\n```json\n{\"action_type\":\"scroll\",\"direction\":\"down\"}\n```\nThat is all.",
        )
        assertEquals("I should scroll.", p.thought)
        assertEquals(HandsAction.Scroll("down"), p.action)
    }

    @Test fun `think blocks are stripped and the last Action wins`() {
        val p = HandsAction.parse(
            "<think>long reasoning Action: {\"action_type\":\"wait\"}</think>Thought: done.\nAction: {\"action_type\":\"status\",\"goal_status\":\"complete\",\"answer\":\"G1234, 08:00, ¥553\"}",
        )
        assertEquals("done.", p.thought)
        val s = p.action as HandsAction.Status
        assertTrue(s.complete)
        assertEquals("G1234, 08:00, ¥553", s.answer)
    }

    @Test fun `aliases from other action spaces are accepted`() {
        assertTrue(HandsAction.fromJson(JSONObject("""{"action":"tap","element":[10,20]}""")) is HandsAction.Click)
        assertTrue(HandsAction.fromJson(JSONObject("""{"action_type":"Long Press","coordinates":[10,20]}""")) is HandsAction.LongPress)
        assertTrue(HandsAction.fromJson(JSONObject("""{"action_type":"type","text":"北京"}""")) is HandsAction.InputText)
        assertTrue(HandsAction.fromJson(JSONObject("""{"action_type":"launch","app":"铁路12306"}""")) is HandsAction.OpenApp)
        assertTrue(HandsAction.fromJson(JSONObject("""{"action_type":"back"}""")) is HandsAction.Back)
        assertTrue(HandsAction.fromJson(JSONObject("""{"action_type":"home"}""")) is HandsAction.Home)
        assertTrue(HandsAction.fromJson(JSONObject("""{"action_type":"enter"}""")) is HandsAction.KeyboardEnter)
        assertTrue(HandsAction.fromJson(JSONObject("""{"action_type":"handoff","reason":"login"}""")) is HandsAction.TakeOver)
        assertTrue(HandsAction.fromJson(JSONObject("""{"action_type":"ask","question":"which date?"}""")) is HandsAction.AskUser)
    }

    @Test fun `swipe with a direction gets an end point`() {
        val s = HandsAction.fromJson(JSONObject("""{"action_type":"swipe","coordinate":[500,800],"direction":"up"}""")) as HandsAction.Swipe
        assertEquals(HandsAction.Point(500, 800), s.from)
        assertEquals(HandsAction.Point(500, 400), s.to)
        val e = HandsAction.fromJson(JSONObject("""{"action_type":"swipe","start_coordinate":[100,500],"end_coordinate":[900,500]}""")) as HandsAction.Swipe
        assertEquals(HandsAction.Point(900, 500), e.to)
    }

    @Test fun `status without goal_status is infeasible unless the verb says done`() {
        val inf = HandsAction.fromJson(JSONObject("""{"action_type":"status","goal_status":"infeasible","answer":"no seats"}""")) as HandsAction.Status
        assertFalse(inf.complete)
        val fin = HandsAction.fromJson(JSONObject("""{"action_type":"finish","answer":"ok"}""")) as HandsAction.Status
        assertTrue(fin.complete)
        val bare = HandsAction.fromJson(JSONObject("""{"action_type":"status","answer":"?"}""")) as HandsAction.Status
        assertFalse(bare.complete)
    }

    @Test fun `wait is clamped`() {
        assertEquals(10, (HandsAction.fromJson(JSONObject("""{"action_type":"wait","seconds":60}""")) as HandsAction.Wait).seconds)
        assertEquals(2, (HandsAction.fromJson(JSONObject("""{"action_type":"wait"}""")) as HandsAction.Wait).seconds)
    }

    @Test fun `bad replies raise FormatError`() {
        assertThrows(HandsAction.Companion.FormatError::class.java) { HandsAction.parse("Thought: hmm") }
        assertThrows(HandsAction.Companion.FormatError::class.java) { HandsAction.parse("Action: click the button") }
        assertThrows(HandsAction.Companion.FormatError::class.java) { HandsAction.fromJson(JSONObject("""{"action_type":"fly"}""")) }
        assertThrows(HandsAction.Companion.FormatError::class.java) { HandsAction.fromJson(JSONObject("""{"action_type":"click"}""")) }
        assertThrows(HandsAction.Companion.FormatError::class.java) { HandsAction.fromJson(JSONObject("""{"action_type":"scroll","direction":"sideways"}""")) }
    }

    @Test fun `json extraction stops at the matching brace and survives braces in strings`() {
        val o = HandsAction.extractJson(""" {"action_type":"input_text","text":"a } b { c","field":"note"} trailing {""")
        assertEquals("a } b { c", o?.getString("text"))
        assertNull(HandsAction.extractJson("no json here"))
        assertNull(HandsAction.extractJson("{unclosed"))
    }

    @Test fun `describe is short and names the target`() {
        assertEquals("tap “立即购买”", HandsAction.Click(HandsAction.Point(1, 1), "立即购买").describe())
        assertEquals("scroll down", HandsAction.Scroll("down").describe())
        assertEquals("open 12306", HandsAction.OpenApp("12306").describe())
        assertEquals("done", HandsAction.Status(true, "x").describe())
    }
}
