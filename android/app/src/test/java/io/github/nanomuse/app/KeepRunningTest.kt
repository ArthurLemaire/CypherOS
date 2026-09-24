package io.github.nanomuse.app

import org.junit.Assert.assertEquals
import org.junit.Test

/** The vendor mapping decides which auto-start page is tried and which advice is shown. */
class KeepRunningTest {
    @Test
    fun vendors_by_manufacturer_and_brand() {
        assertEquals("xiaomi", KeepRunning.vendor("Xiaomi", "Redmi"))
        assertEquals("xiaomi", KeepRunning.vendor("Xiaomi", "POCO"))
        assertEquals("huawei", KeepRunning.vendor("HUAWEI", "HUAWEI"))
        assertEquals("honor", KeepRunning.vendor("HONOR", "HONOR"))
        assertEquals("oppo", KeepRunning.vendor("OPPO", "OPPO"))
        assertEquals("oppo", KeepRunning.vendor("realme", "realme"))
        assertEquals("oppo", KeepRunning.vendor("OnePlus", "OnePlus"))
        assertEquals("vivo", KeepRunning.vendor("vivo", "vivo"))
        assertEquals("vivo", KeepRunning.vendor("vivo", "iQOO"))
        assertEquals("samsung", KeepRunning.vendor("samsung", "samsung"))
        assertEquals("meizu", KeepRunning.vendor("Meizu", "Meizu"))
        assertEquals("", KeepRunning.vendor("Google", "google"))
        assertEquals("", KeepRunning.vendor("unknown", "Android"))
    }
}
