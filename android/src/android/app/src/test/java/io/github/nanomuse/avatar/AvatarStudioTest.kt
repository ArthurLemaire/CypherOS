package io.github.nanomuse.avatar

import io.github.nanomuse.ui.avatar.AgentMood
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AvatarStudioTest {

    @Test fun `four candidates get four different prompts from one description`() {
        val prompts = (0 until 4).map { AvatarStudio.buildPrompt("A round red panda", AvatarStudio.Style.FLAT, it) }
        assertEquals(4, prompts.toSet().size)
        prompts.forEach {
            assertTrue(it.contains("A round red panda. "))
            assertTrue(it.contains(AvatarStudio.Style.FLAT.phrase))
            assertTrue(it.contains("No text"))
            // Muse's house rules: whole figure, facing you, white ground, square.
            assertTrue(it.contains("Full body"))
            assertTrue(it.contains("pure white background"))
            assertTrue(it.contains("Square composition"))
        }
        // The fifth candidate wraps around instead of crashing.
        assertEquals(prompts[0], AvatarStudio.buildPrompt("A round red panda", AvatarStudio.Style.FLAT, 4))
    }

    @Test fun `the default style is the 3D toy look`() {
        assertEquals(AvatarStudio.Style.MUSE, AvatarStudio.Style.byId(null))
        assertEquals(AvatarStudio.Style.MUSE, AvatarStudio.Style.byId("nonsense"))
        assertTrue(AvatarStudio.Style.MUSE.phrase.contains("3D"))
    }

    @Test fun `a trailing full stop in the description is not doubled`() {
        val p = AvatarStudio.buildPrompt("  一只圆滚滚的小熊猫。 ", AvatarStudio.Style.CLAY, 0)
        assertTrue(p.contains("一只圆滚滚的小熊猫. "))
        assertFalse(p.contains(".."))
        assertFalse(p.contains("。."))
    }

    @Test fun `every mood but idle gets a pose that keeps the character`() {
        for (mood in AgentMood.entries.filter { it != AgentMood.IDLE }) {
            val i = AvatarStudio.moodInstruction(mood)
            assertTrue(mood.name, i.startsWith("Keep this exact character"))
            assertTrue(mood.name, i.length > 80)
        }
        assertTrue(AvatarStudio.moodInstruction(AgentMood.WORKING).contains("headphones"))
        assertTrue(AvatarStudio.moodInstruction(AgentMood.WAITING).contains("crystal ball"))
        assertTrue(AvatarStudio.moodInstruction(AgentMood.HAPPY).contains("star"))
    }

    @Test fun `rate limits are recognised however the provider phrases them`() {
        assertTrue(AvatarStudio.looksRateLimited(RuntimeException("HTTP 429 Too Many Requests")))
        assertTrue(AvatarStudio.looksRateLimited(RuntimeException("Rate limited — please try again later")))
        assertTrue(AvatarStudio.looksRateLimited(RuntimeException("Throttling.RateQuota")))
        assertFalse(AvatarStudio.looksRateLimited(RuntimeException("HTTP 401 invalid api key")))
        assertFalse(AvatarStudio.looksRateLimited(RuntimeException(null as String?)))
    }
}
