package io.github.nanomuse.onboarding

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FirstConversationTest {

    @Test fun `an address block carries the address and two suggestions`() {
        val reply = "好的，Lin，记住了！那我呢——你想叫我什么？\n\n```nanomuse-naming\n{\"user_address\": \"Lin\", \"suggest\": [\"豆丁\", \"小满\"]}\n```"
        val b = FirstConversation.parseBlock(reply)!!
        assertTrue(b.addressGiven)
        assertEquals("Lin", b.userAddress)
        assertEquals(listOf("豆丁", "小满"), b.suggestions)
        assertNull(b.agentName)
    }

    @Test fun `no address wanted is still a step forward`() {
        val b = FirstConversation.parseBlock("Fine — no name then. What would you like to call me?\n```nanomuse-naming\n{\"user_address\": null, \"suggest\": [\"Pip\", \"Wren\"]}\n```")!!
        assertTrue(b.addressGiven)
        assertNull(b.userAddress)
        assertEquals(listOf("Pip", "Wren"), b.suggestions)
    }

    @Test fun `a detour has no block and changes nothing`() {
        assertNull(FirstConversation.parseBlock("今天上海多云，22 度左右。对了——我该怎么称呼你？"))
        assertNull(FirstConversation.parseBlock(null))
        assertNull(FirstConversation.parseBlock("```nanomuse-naming\nnot json\n```"))
    }

    @Test fun `the agent name block names the agent`() {
        val b = FirstConversation.parseBlock("豆丁，我喜欢这个名字。\n\n- …\n\n```nanomuse-naming\n{\"agent_name\": \"豆丁\"}\n```")!!
        assertFalse(b.addressGiven)
        assertEquals("豆丁", b.agentName)
        assertTrue(b.suggestions.isEmpty())
    }

    @Test fun `names are cleaned and bounded`() {
        assertEquals("豆丁", FirstConversation.cleanName("「豆丁」。"))
        assertEquals("Pip", FirstConversation.cleanName(" \"Pip\" "))
        assertNull(FirstConversation.cleanName(""))
        assertNull(FirstConversation.cleanName("a name that is far too long to be a name"))
        assertNull(FirstConversation.cleanName("two\nlines"))
    }

    @Test fun `the last block wins and suggestions are capped`() {
        val text = "```nanomuse-naming\n{\"agent_name\": \"A\"}\n```\nlater\n```nanomuse-naming\n{\"user_address\": \"Kai\", \"suggest\": [\"a\", \"b\", \"c\", \"d\", \"a\"]}\n```"
        val b = FirstConversation.parseBlock(text)!!
        assertEquals("Kai", b.userAddress)
        assertEquals(listOf("a", "b", "c"), b.suggestions)
        assertNull(b.agentName)
    }
}
