---
name: responsive-design
description: Design for multiple screen sizes — mobile, tablet, desktop, plus larger displays. Mobile-first by default. Breakpoint strategy, fluid sizing, container queries. Without responsive discipline, designs work on designer's monitor and fail everywhere else.
---

# Responsive Design — One Design, Many Screens

A 4-screen design (mobile, tablet, desktop, wide) takes 1.5x effort of single design. Skipping responsiveness fails 50%+ of users (varies by audience). Responsive discipline integrates from the start.

## Prerequisites

- `wireframe-production` understood
- `design-tokens-discipline` for breakpoint tokens
- Project type clear (mobile-first, desktop-first, etc.)

## Core principle

> Design for the smallest screen first. Add complexity as space allows. Reverse direction (desktop first, scale down) almost always fails because constraints are tighter at small sizes — design that assumes space rarely fits when space removed.

## Breakpoint strategy

**Standard breakpoints (Fosved default):**

```
xs: 0      (mobile portrait, default)
sm: 640px  (mobile landscape, small tablet portrait)
md: 768px  (tablet portrait)
lg: 1024px (tablet landscape, small desktop)
xl: 1280px (desktop)
2xl: 1536px (wide desktop)
```

These match Tailwind defaults — code aligned with design.

**Use:**
- `xs` to `sm`: phone-only optimizations
- `md` and up: tablet+ layouts (often unified)
- `lg` and up: full desktop layouts
- `2xl`: max-width constraints, prevent content stretching too wide

## Mobile-first approach

Design narrowest, then widen:

1. Wireframe mobile (320-640px)
2. Decide: at what width does mobile fall apart?
3. Design tablet view at that breakpoint
4. Decide: at what width does tablet feel cramped?
5. Design desktop view

Each step asks: what changes? Not just "make bigger."

## Common responsive patterns

### Stack to side-by-side

Mobile: stacked vertically.
Desktop: side-by-side.

Common for: hero + content, form + preview, sidebar + main.

### Hamburger to nav bar

Mobile: hamburger icon, menu in drawer.
Desktop: nav links visible in bar.

### Card grid scaling

Mobile: 1 column.
Tablet: 2 columns.
Desktop: 3-4 columns.

### Truncate vs reveal

Mobile: truncated description, "see more" link.
Desktop: full content visible.

### Modal vs inline

Mobile: full-screen overlay.
Desktop: inline panel or smaller modal.

### Tabs vs accordion

Mobile: vertical accordion.
Desktop: horizontal tabs.

These aren't rules — they're patterns. Each project chooses based on tasks and content.

## What actually changes per breakpoint

Not everything. Some elements stable:
- Brand identity (logo, colors, fonts)
- Component appearance (button looks same shape, just maybe different size)
- Voice and tone
- Information hierarchy (still the same priority)

What changes:
- **Layout:** how elements arranged (stacked vs side-by-side)
- **Navigation:** how user moves around
- **Content density:** how much shown at once
- **Touch targets:** larger on mobile (44px+) than desktop
- **Imagery:** different crops for different aspects
- **Text:** sometimes shorter on mobile

## Fluid sizing

Beyond breakpoints, use fluid sizing for smooth scaling:

**Fluid type:**
```css
font-size: clamp(1rem, 2vw + 0.5rem, 2rem);
/* scales smoothly between viewport min/max */
```

**Fluid spacing:**
```css
padding: clamp(1rem, 4vw, 4rem);
```

Adapts within breakpoint, not just at threshold. Smoother UX.

But: tokens should still control bounds. Don't fluidify everything (loses consistency).

## Container queries

Modern feature: components respond to their container size, not viewport.

```css
@container card (min-width: 400px) {
  .card-content {
    /* styles for cards in containers ≥400px */
  }
}
```

Useful when:
- Card in main column vs sidebar (same component, different containers)
- Reusable component dropped in various places

Browser support good as of 2026. Use where applicable.

## Touch vs mouse

Mobile = touch. Touch interactions different from mouse:

**Touch:**
- Minimum 44×44px targets
- No hover (or hover = first tap)
- Gestures supported (swipe, pinch)
- Thumb-friendly (bottom navigation often)

**Mouse:**
- Smaller targets ok (24×24px+)
- Hover meaningful
- Precise pointing

**Hybrid devices (touchscreen laptops, iPad with mouse):**
- Design for both
- Don't put critical actions in hover-only
- Cursor pointer + touch friendly

## Performance considerations

Mobile users on slower connections — design must perform:

- Images: serve appropriate size per device
- Lazy-load below-fold content
- Reduce JS bundle size
- Avoid blocking renders

Even great-looking design fails if slow on mobile.

## Mobile-specific UX

Mobile context often different:
- One-handed use
- Outdoor (sunlight, glare)
- Distracted (split attention)
- Short sessions

Designs:
- Big touch targets
- High contrast
- Single primary action visible
- Forgive interruptions (preserve state)

## Testing responsive designs

Don't just resize browser. Test on:

- Real mobile devices (multiple)
- Real tablets
- Slow connections (throttle network)
- Different OS (iOS, Android — render differently)

DevTools device emulation: starting point, not sufficient.

## Common responsive failures

**Designed at 1440px wide.** Default browser size. Mobile broken.

**Tiny touch targets on mobile.** Designed for mouse precision. Frustrating on phone.

**Text too small.** Mobile minimum 16px body (preferable to prevent iOS auto-zoom).

**Modals too big for mobile.** Cover whole screen unintentionally or overflow.

**Tables on mobile.** Wide tables horizontal-scroll. Often need redesign (cards on mobile, table on desktop).

**Image not responsive.** Doesn't scale, breaks layout.

**Fixed pixel values.** `width: 1024px` — breaks below 1024.

**Hover-only menu.** No access on touch.

## Responsive checklist

For each design:

- [ ] Mobile design exists (not just desktop scaled)
- [ ] Tablet design exists (or noted as same-as-mobile or same-as-desktop)
- [ ] Desktop design exists
- [ ] Touch targets ≥44px on mobile
- [ ] Text ≥16px body on mobile (no iOS auto-zoom)
- [ ] Navigation accessible on each breakpoint
- [ ] Content readable on each (line length 50-80 chars)
- [ ] Images scale or have appropriate variants
- [ ] No horizontal scroll (unless intentional)
- [ ] All interactive elements work on touch
- [ ] State preservation across orientation changes
- [ ] Tested on real devices

## Responsive variants in DesignArtifact

Stored as separate variants:
```javascript
{
  hasResponsiveVariants: true,
  mobileVariant: '<svg>...</svg>',
  tabletVariant: '<svg>...</svg>',
  desktopVariant: '<svg>...</svg>'
}
```

Each variant a complete design at that breakpoint. Dev implements all.

## Anti-patterns

- **Desktop-first.** Designed for big screen, retrofitted for mobile. Always feels compromised.
- **Hide content on mobile.** Mobile users see less. Often important info hidden.
- **Mobile is afterthought.** Designed at end, no time for proper design.
- **Same density everywhere.** Cramming desktop info into mobile.
- **Fixed pixel widths.** `width: 1200px` breaks at 1199px.
- **No empty state per breakpoint.** Empty looks fine on desktop, broken on mobile.
- **One breakpoint everywhere.** Tablet design = desktop design, looks awkward.
- **Hover for critical info.** Mobile users can't access.
- **Tiny modal close button.** Fat-finger hits content behind.
- **No landscape consideration.** Phone landscape, tablet portrait differ from defaults.

## Integration

- `wireframe-production` includes responsive variants
- `interaction-states` may have mobile-specific states
- `dev-handoff-specs` includes breakpoint specifications
- `design-tokens-discipline` defines breakpoint tokens
- DesignArtifact stores variants per breakpoint
