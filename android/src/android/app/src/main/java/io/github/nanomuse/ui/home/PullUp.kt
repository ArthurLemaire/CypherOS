package io.github.nanomuse.ui.home

import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.layout
import androidx.compose.ui.unit.Dp

/**
 * A negative top margin: the element is laid out [by] higher than its slot and the slot
 * shrinks to match, so what follows moves up too (unlike `offset`, which only shifts drawing).
 * Used to hang the name pill off the avatar disc.
 */
fun pullUp(by: Dp): Modifier = Modifier.layout { measurable, constraints ->
    val placeable = measurable.measure(constraints)
    val shift = by.roundToPx()
    layout(placeable.width, (placeable.height - shift).coerceAtLeast(0)) {
        placeable.placeRelative(0, -shift)
    }
}
