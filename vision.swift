// Mac helpers for clipper.py, using frameworks already on the machine.
//   vision faces IMG...     one line per image: "x y width" of the largest face (0-1, y from top), or "null"
//   vision captions SPEC    draw the transparent caption images listed in a JSON spec
import AppKit
import Vision

struct Word: Decodable { let t: String; let hl: Bool }
struct Item: Decodable { let path: String; let words: [Word] }
struct Spec: Decodable {
    let width: Int, height: Int, size: Double, stroke_width: Double
    let font: String, color: String, highlight: String, stroke: String
    let items: [Item]
}

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

func text(_ s: Spec, _ item: Item, stroke: Bool) -> NSAttributedString {
    let font = NSFont(name: s.font, size: s.size) ?? NSFont.boldSystemFont(ofSize: s.size)
    let para = NSMutableParagraphStyle()
    para.alignment = .center
    let out = NSMutableAttributedString()
    for (i, w) in item.words.enumerated() {
        var a: [NSAttributedString.Key: Any] = [.font: font, .paragraphStyle: para]
        if stroke {
            a[.strokeColor] = hex(s.stroke)
            a[.strokeWidth] = s.stroke_width  // positive means outline only
        } else {
            a[.foregroundColor] = hex(w.hl ? s.highlight : s.color)
        }
        out.append(NSAttributedString(string: (i > 0 ? " " : "") + w.t, attributes: a))
    }
    return out
}

func captions(_ path: String) throws {
    let s = try JSONDecoder().decode(Spec.self, from: Data(contentsOf: URL(fileURLWithPath: path)))
    for item in s.items {
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: s.width, pixelsHigh: s.height,
                                   bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                   colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        NSGraphicsContext.current!.cgContext.setLineJoin(.round)  // no spikes on thick outlines
        if !item.words.isEmpty {
            let box = NSRect(x: 50, y: 0, width: s.width - 100, height: s.height)
            let fill = text(s, item, stroke: false)
            let h = fill.boundingRect(with: box.size, options: .usesLineFragmentOrigin).height
            let r = NSRect(x: box.minX, y: (CGFloat(s.height) - h) / 2, width: box.width, height: h)
            text(s, item, stroke: true).draw(with: r, options: .usesLineFragmentOrigin)
            fill.draw(with: r, options: .usesLineFragmentOrigin)
        }
        NSGraphicsContext.current = nil
        try rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: item.path))
    }
}

let args = Array(CommandLine.arguments.dropFirst())
if args.first == "faces" { faces(Array(args.dropFirst())) }
else if args.first == "captions", args.count == 2 { try captions(args[1]) }
else { fputs("usage: vision faces IMG... | vision captions SPEC\n", stderr); exit(2) }
