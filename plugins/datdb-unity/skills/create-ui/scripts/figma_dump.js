// Read-only use_figma script for the create-ui skill (step 1 + 2 in ONE Figma call).
// Replace __NODE_ID__ with the frame id ("A:B"). Returns the font list AND every node's properties, hidden ones
// included, so neither get_metadata nor a second use_figma call is needed. Save the returned JSON as
// <scratchpad>/build_<name>/figma_dump.json; figma_spec.py reads it.
const FRAME_ID = "__NODE_ID__";
const frame = await figma.getNodeByIdAsync(FRAME_ID);
if (!frame) throw new Error("node not found: " + FRAME_ID);
const fb = frame.absoluteBoundingBox;
const r2 = (v) => Math.round(v * 100) / 100;
const rgb = (c) => [c.r, c.g, c.b].map((v) => Math.round(v * 255));
const paints = (ps) => (Array.isArray(ps) ? ps.map((p) => {
  const d = { type: p.type };
  if (p.visible === false) d.visible = false;
  if (p.opacity !== undefined && p.opacity !== 1) d.opacity = r2(p.opacity);
  if (p.color) d.color = rgb(p.color);
  if (p.imageHash) { d.imageHash = p.imageHash; d.scaleMode = p.scaleMode; }
  if (p.gradientStops) {   // [position, r, g, b, a0-1]; transform maps the node's unit box to gradient space
    d.stops = p.gradientStops.map((s) => [r2(s.position)].concat(rgb(s.color), [r2(s.color.a)]));
    d.transform = p.gradientTransform.map((row) => row.map((v) => Math.round(v * 10000) / 10000));
  }
  return d;
}) : "mixed");
const box = (b) => (b ? [r2(b.x - fb.x), r2(b.y - fb.y), r2(b.width), r2(b.height)] : null);
const fonts = {};
const nodes = [];

function walk(n, parent) {
  const d = { id: n.id, name: n.name, type: n.type, parent, visible: n.visible, bbox: box(n.absoluteBoundingBox) };
  if ("absoluteRenderBounds" in n) d.render = box(n.absoluteRenderBounds);
  if ("opacity" in n && n.opacity !== 1) d.opacity = r2(n.opacity);
  if ("fills" in n) d.fills = paints(n.fills);
  if ("strokes" in n && n.strokes.length) {
    d.strokes = paints(n.strokes);
    d.strokeWeight = typeof n.strokeWeight === "number" ? n.strokeWeight : "mixed";
    d.strokeAlign = n.strokeAlign;
  }
  if ("effects" in n && n.effects.length) d.effects = n.effects.map((e) => ({
    type: e.type, visible: e.visible, radius: e.radius, spread: e.spread,
    color: e.color ? rgb(e.color).concat([r2(e.color.a)]) : undefined,
    offset: e.offset ? [e.offset.x, e.offset.y] : undefined,
  }));
  if ("cornerRadius" in n && typeof n.cornerRadius === "number" && n.cornerRadius) d.cornerRadius = n.cornerRadius;
  if (n.type === "TEXT") {
    const mixed = n.fontName === figma.mixed || n.fontSize === figma.mixed || !Array.isArray(n.fills);
    const fontName = n.fontName === figma.mixed ? n.getRangeFontName(0, 1) : n.fontName;
    d.characters = n.characters;
    d.font = fontName.family + " " + fontName.style;
    d.fontSize = n.fontSize === figma.mixed ? n.getRangeFontSize(0, 1) : n.fontSize;
    if (!Array.isArray(n.fills)) d.fills = paints(n.getRangeFills(0, 1));
    d.lineHeight = n.lineHeight === figma.mixed ? "mixed" : n.lineHeight;
    d.letterSpacing = n.letterSpacing === figma.mixed ? "mixed" : n.letterSpacing;
    d.textAlign = n.textAlignHorizontal;
    d.textAlignVertical = n.textAlignVertical;
    d.autoResize = n.textAutoResize;
    if (mixed) d.mixed = true;
    (fonts[d.font] = fonts[d.font] || []).push(n.name);
  }
  nodes.push(d);
  if ("children" in n) for (const c of n.children) walk(c, n.id);
}

walk(frame, null);
return { frame: { id: frame.id, name: frame.name, w: fb.width, h: fb.height }, fonts, nodes };
