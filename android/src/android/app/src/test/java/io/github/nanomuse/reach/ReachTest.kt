package io.github.nanomuse.reach

import io.github.nanomuse.ui.reach.parseAddress
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ReachTest {

    @Test fun `addresses as the host prints them`() {
        assertEquals("192.168.1.23" to 7333, parseAddress("192.168.1.23:7333"))
        assertEquals("192.168.1.23" to 7333, parseAddress("  192.168.1.23 "))
        assertEquals("my-mac.local" to 8000, parseAddress("http://my-mac.local:8000/"))
        assertEquals("10.0.0.5" to 7333, parseAddress("https://10.0.0.5"))
    }

    @Test fun `bad addresses are refused`() {
        assertNull(parseAddress(""))
        assertNull(parseAddress("192.168.1.23:abc"))
        assertNull(parseAddress("192.168.1.23:70000"))
        assertNull(parseAddress("two words:7333"))
    }

    @Test fun `a computer knows its urls`() {
        val c = Computers.Computer("id", "desk", "Linux", "192.168.1.23", 7333, "t", 0L)
        assertEquals("192.168.1.23:7333", c.address)
        assertEquals("http://192.168.1.23:7333/shell", c.url("/shell"))
    }

    @Test fun `the help names every verb`() {
        for (verb in listOf("status", "run", "ls", "get", "put", "open", "screen")) {
            assertTrue(verb, ReachOffloadHandler.HELP.contains("nanomuse-pc $verb"))
        }
    }
}
