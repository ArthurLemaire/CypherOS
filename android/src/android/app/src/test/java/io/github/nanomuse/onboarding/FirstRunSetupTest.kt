package io.github.nanomuse.onboarding

import io.github.nanomuse.ui.onboarding.FirstRunSetup
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FirstRunSetupTest {

    @Test
    fun `a fresh install is walked through the setup until Start`() {
        assertTrue(FirstRunSetup.needed(hasProviders = false, hasSessions = false, done = false))
        // Provider added, models picked, but Start not tapped yet: still the welcome screen.
        assertTrue(FirstRunSetup.needed(hasProviders = true, hasSessions = false, done = false))
        assertFalse(FirstRunSetup.needed(hasProviders = true, hasSessions = false, done = true))
    }

    @Test
    fun `an existing install with conversations never sees the setup`() {
        assertFalse(FirstRunSetup.needed(hasProviders = true, hasSessions = true, done = false))
        assertFalse(FirstRunSetup.needed(hasProviders = true, hasSessions = true, done = true))
    }

    @Test
    fun `losing every provider brings the setup back, whatever else is true`() {
        assertTrue(FirstRunSetup.needed(hasProviders = false, hasSessions = true, done = true))
    }

    @Test
    fun `the Continue button performs the first incomplete step`() {
        assertEquals(1, FirstRunSetup.currentStep(hasProviders = false, hasGroups = false))
        assertEquals(2, FirstRunSetup.currentStep(hasProviders = true, hasGroups = false))
        assertEquals(3, FirstRunSetup.currentStep(hasProviders = true, hasGroups = true))
    }
}
