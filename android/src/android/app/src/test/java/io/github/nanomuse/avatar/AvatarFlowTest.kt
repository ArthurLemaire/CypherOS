package io.github.nanomuse.avatar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AvatarFlowTest {

    @Test fun `chinese requests name the new face`() {
        assertEquals("一只小狗", AvatarFlow.parseRequest("把虚拟形象换成一只小狗"))
        assertEquals("小猫咪", AvatarFlow.parseRequest("帮我把虚拟形象换成小猫咪"))
        assertEquals("戴眼镜的熊猫", AvatarFlow.parseRequest("把你的形象改成戴眼镜的熊猫吧"))
        assertEquals("柯基", AvatarFlow.parseRequest("换个形象：柯基"))
        assertEquals("小狗", AvatarFlow.parseRequest("把虚拟形象改成 小狗"))
        assertEquals("一只机器猫", AvatarFlow.parseRequest("变成一只机器猫的形象"))
    }

    @Test fun `english requests name the new face`() {
        assertEquals("corgi", AvatarFlow.parseRequest("Change your avatar to a corgi"))
        assertEquals("robot fox", AvatarFlow.parseRequest("please switch the avatar into a robot fox."))
        assertEquals("panda with glasses", AvatarFlow.parseRequest("new avatar: panda with glasses"))
        assertEquals("cat", AvatarFlow.parseRequest("become a cat"))
    }

    @Test fun `ordinary messages are not requests`() {
        assertNull(AvatarFlow.parseRequest("帮我查一下明天的天气"))
        assertNull(AvatarFlow.parseRequest("形象工程是什么意思"))
        assertNull(AvatarFlow.parseRequest("be quiet"))
        assertNull(AvatarFlow.parseRequest("become better at math"))
        assertNull(AvatarFlow.parseRequest("what is an avatar"))
        assertNull(AvatarFlow.parseRequest("我的头像在哪里改？"))
        assertNull(AvatarFlow.parseRequest(""))
    }

    @Test fun `a pick can be typed in either language`() {
        assertEquals(AvatarFlow.Choice.Index(0), AvatarFlow.parseChoice("第一个"))
        assertEquals(AvatarFlow.Choice.Index(1), AvatarFlow.parseChoice("就第二个吧"))
        assertEquals(AvatarFlow.Choice.Index(3), AvatarFlow.parseChoice("4"))
        assertEquals(AvatarFlow.Choice.Index(2), AvatarFlow.parseChoice("Option 3"))
        assertEquals(AvatarFlow.Choice.Index(0), AvatarFlow.parseChoice("the first one"))
        assertEquals(AvatarFlow.Choice.Index(3), AvatarFlow.parseChoice("右下"))
        assertEquals(AvatarFlow.Choice.Regenerate, AvatarFlow.parseChoice("再来一组"))
        assertEquals(AvatarFlow.Choice.Regenerate, AvatarFlow.parseChoice("regenerate"))
        assertNull(AvatarFlow.parseChoice("其实我想问个别的问题"))
        assertNull(AvatarFlow.parseChoice("5"))
    }

    @Test fun `the persisted fence carries the pick`() {
        val fence = AvatarFlow.optionsFence("小狗", 2, listOf("/a/0.png", "/a/1.png", "/a/2.png", "/a/3.png"))
        assert(fence.startsWith("```" + AvatarFlow.BLOCK_OPTIONS + "\n"))
        assert(fence.contains("\"chosen\":2"))
        assert(fence.contains("/a/3.png"))
        assert(fence.trimEnd().endsWith("```"))
    }
}
