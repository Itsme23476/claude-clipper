// Mac helpers for clipper.py, using frameworks already on the machine.
//   vision faces IMG...     one line per image: "x y width" of the largest face (0-1, y from top), or "null"
//   vision captions SPEC    draw the transparent caption images listed in a JSON spec, one or more lines each
import AppKit
import Vision

// on: false keeps its space but hides it. c, f, z: a highlighted word's own colour, font and size multiplier.
struct Word: Decodable { let t: String; let hl: Bool; let on: Bool; let c: String?; let f: String?; let z: Double? }
struct Look: Decodable {
    let font: String, size: Double, color: String, highlight: String, highlight_font: String, highlight_scale: Double
    let stroke: String, stroke_width: Double, shadow: Double, stagger: Double, box: String, align: String
}
struct Item: Decodable { let path: String; let lines: [[Word]]; let look: Look }
struct Spec: Decodable { let width: Int, height: Int; let items: [Item] }

func hex(_ s: String) -> NSColor {
    var v: UInt64 = 0
    Scanner(string: s.replacingOccurrences(of: "#", with: "")).scanHexInt64(&v)
    return NSColor(srgbRed: CGFloat((v >> 16) & 255) / 255, green: CGFloat((v >> 8) & 255) / 255,
                   blue: CGFloat(v & 255) / 255, alpha: 1)
}

func faces(_ paths: [String]) {
    for p in paths {
        guard let img = NSImage(contentsOfFile: p),
              let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { print("null"); continue }
        let req = VNDetectFaceRectanglesRequest()
        try? VNImageRequestHandler(cgImage: cg).perform([req])
        if let b = (req.results ?? []).max(by: { $0.boundingBox.width < $1.boundingBox.width })?.boundingBox {
            print("\(b.midX) \(1 - b.midY) \(b.width)")
        } else { print("null") }
    }
}

func text(_ k: Look, _ words: [Word], stroke: Bool, fit: Double = 1) -> NSAttributedString {
    let font = NSFont(name: k.font, size: k.size * fit) ?? NSFont.boldSystemFont(ofSize: k.size * fit)
    let para = NSMutableParagraphStyle()
    para.alignment = k.align == "left" ? .left : .center
    let shadow = NSShadow()
    shadow.shadowBlurRadius = k.shadow
    shadow.shadowOffset = NSSize(width: 0, height: -k.shadow / 4)
    shadow.shadowColor = NSColor(white: 0, alpha: 0.8)
    let out = NSMutableAttributedString()
    for (i, w) in words.enumerated() {
        let z = k.size * fit * (w.z ?? k.highlight_scale)
        let big = NSFont(name: w.f ?? k.highlight_font, size: z) ?? font.withSize(z)
        var a: [NSAttributedString.Key: Any] = [.font: w.hl ? big : font, .paragraphStyle: para]
        if stroke {
            a[.strokeColor] = w.on ? hex(k.stroke) : NSColor.clear
            a[.strokeWidth] = k.stroke_width  // positive means outline only
        } else {
            a[.foregroundColor] = w.on ? hex(w.c ?? (w.hl ? k.highlight : k.color)) : NSColor.clear
            if w.on && k.shadow > 0 { a[.shadow] = shadow }
        }
        out.append(NSAttributedString(string: (i > 0 ? " " : "") + w.t, attributes: a))
    }
    return out
}

func captions(_ path: String) throws {
    let s = try JSONDecoder().decode(Spec.self, from: Data(contentsOf: URL(fileURLWithPath: path)))
    let W = CGFloat(s.width), maxW = W - 100
    for item in s.items {
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: s.width, pixelsHigh: s.height,
                                   bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                   colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        NSGraphicsContext.current!.cgContext.setLineJoin(.round)  // no spikes on thick outlines
        let k = item.look
        // a single word too wide for the frame shrinks to fit instead of breaking mid-word
        let fits = item.lines.map { $0.count == 1 ? min(1, Double(maxW) / max(text(k, $0, stroke: false).size().width, 1)) : 1 }
        let fills = item.lines.indices.map { text(k, item.lines[$0], stroke: false, fit: fits[$0]) }
        let sizes = fills.map { $0.boundingRect(with: NSSize(width: maxW, height: 2000), options: .usesLineFragmentOrigin).size }
        let gap = sizes.count > 1 ? -0.12 * k.size : 0  // stacked lines sit tight
        var top = (CGFloat(s.height) + sizes.reduce(0) { $0 + $1.height } + gap * CGFloat(sizes.count - 1)) / 2
        var rects: [NSRect] = []
        for (i, sz) in sizes.enumerated() {  // each line centred, then stepped right by `stagger`
            let w = ceil(sz.width) + 2
            let x = k.align == "left" ? 0.12 * W : (W - w) / 2 + (CGFloat(i) - CGFloat(sizes.count - 1) / 2) * k.stagger
            rects.append(NSRect(x: min(max(x, 10), W - w - 10), y: top - sz.height, width: w, height: sz.height))
            top -= sz.height + gap
        }
        if !k.box.isEmpty, let first = rects.first {
            hex(k.box).setFill()
            NSBezierPath(rect: rects.reduce(first) { $0.union($1) }.insetBy(dx: -0.3 * k.size, dy: -0.1 * k.size)).fill()
        }
        for (i, r) in rects.enumerated() {
            if k.stroke_width > 0 { text(k, item.lines[i], stroke: true, fit: fits[i]).draw(with: r, options: .usesLineFragmentOrigin) }
            fills[i].draw(with: r, options: .usesLineFragmentOrigin)
            if k.shadow > 0 { fills[i].draw(with: r, options: .usesLineFragmentOrigin) }  // twice: darker halo on light shirts
        }
        NSGraphicsContext.current = nil
        try rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: item.path))
    }
}

let args = Array(CommandLine.arguments.dropFirst())
if args.first == "faces" { faces(Array(args.dropFirst())) }
else if args.first == "captions", args.count == 2 { try captions(args[1]) }
else { fputs("usage: vision faces IMG... | vision captions SPEC\n", stderr); exit(2) }
