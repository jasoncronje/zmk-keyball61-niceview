// ptrec: records what the Mac receives from every pointing device, so a
// trackball can be compared with a known-good mouse using numbers, not feel.
//
// Two streams, one CSV on stdout:
//   hid  every raw HID input report from each mouse/pointer device, with the
//        kernel's arrival timestamp, the transport, and the report bytes
//   val  the X / Y element values macOS parsed from those reports
//   cg   every pointer event macOS produced (listen-only event tap): the
//        on-screen position and the delta after macOS's own scaling
//
// Columns: kind,t_us,device,transport,a,b,extra
//   hid: a = report id, b = length, extra = hex bytes
//   val: a = usage (0x30 X, 0x31 Y, 0x38 wheel), b = value
//   dev: a = 1 if readable, 0 if another program holds it exclusively
//   cg : a = dx, b = dy (macOS deltas), extra = "x y" screen position
// t_us is microseconds on the mach clock (the same clock for all rows).
//
// Build: swiftc -O -o ptrec tools/pointerbench/ptrec.swift
// Run:   ./ptrec 30 > capture.csv      (seconds; Ctrl-C stops early)

import CoreGraphics
import Foundation
import IOKit.hid

setvbuf(stdout, nil, _IOFBF, 1 << 16)

var timebase = mach_timebase_info_data_t()
mach_timebase_info(&timebase)
func micros(_ ticks: UInt64) -> UInt64 {
    return ticks * UInt64(timebase.numer) / UInt64(timebase.denom) / 1000
}

func err(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }

func prop(_ dev: IOHIDDevice, _ key: String) -> String {
    guard let v = IOHIDDeviceGetProperty(dev, key as CFString) else { return "?" }
    return "\(v)".replacingOccurrences(of: ",", with: " ")
}

final class Dev {
    let name: String
    let transport: String
    let buf: UnsafeMutablePointer<UInt8>
    let len: Int
    init(_ d: IOHIDDevice) {
        name = prop(d, kIOHIDProductKey)
        transport = prop(d, kIOHIDTransportKey).contains("Bluetooth") ? "ble" : prop(d, kIOHIDTransportKey).lowercased()
        len = max(64, (IOHIDDeviceGetProperty(d, kIOHIDMaxInputReportSizeKey as CFString) as? Int) ?? 64)
        buf = UnsafeMutablePointer<UInt8>.allocate(capacity: len)
    }
}

var devs: [IOHIDDevice: Dev] = [:]
var seen = Set<UInt64>()

let manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
let matches: [[String: Int]] = [
    [kIOHIDDeviceUsagePageKey: kHIDPage_GenericDesktop, kIOHIDDeviceUsageKey: kHIDUsage_GD_Mouse],
    [kIOHIDDeviceUsagePageKey: kHIDPage_GenericDesktop, kIOHIDDeviceUsageKey: kHIDUsage_GD_Pointer],
]
IOHIDManagerSetDeviceMatchingMultiple(manager, matches as CFArray)

let reportCallback: IOHIDReportWithTimeStampCallback = { ctx, _, _, _, reportID, report, length, timeStamp in
    let d = Unmanaged<Dev>.fromOpaque(ctx!).takeUnretainedValue()
    var hex = ""
    for i in 0..<length { hex += String(format: "%02x", report[i]) }
    print("hid,\(micros(timeStamp)),\(d.name),\(d.transport),\(reportID),\(length),\(hex)")
}

IOHIDManagerRegisterDeviceMatchingCallback(manager, { _, _, _, device in
    // Each device matches both usages above, so it arrives twice.
    var entry: UInt64 = 0
    IORegistryEntryGetRegistryEntryID(IOHIDDeviceGetService(device), &entry)
    if seen.contains(entry) { return }
    seen.insert(entry)
    let d = Dev(device)
    devs[device] = d
    let r = IOHIDDeviceOpen(device, IOOptionBits(kIOHIDOptionsTypeNone))
    // 0xe00002c5 = another program (Karabiner-Elements, usually) holds the
    // device exclusively: its reports never reach us or macOS directly.
    err("device: \(d.name) [\(d.transport)] " + (r == kIOReturnSuccess ? "open" : String(format: "NOT READABLE 0x%08x", r)))
    print("dev,0,\(d.name),\(d.transport),\(r == kIOReturnSuccess ? 1 : 0),0,\(prop(device, "HIDPointerResolution")) \(prop(device, kIOHIDReportIntervalKey))")
    IOHIDDeviceRegisterInputReportWithTimeStampCallback(
        device, d.buf, d.len, reportCallback, Unmanaged.passUnretained(d).toOpaque())
}, nil)

IOHIDManagerRegisterInputValueCallback(manager, { _, _, sender, value in
    let el = IOHIDValueGetElement(value)
    guard IOHIDElementGetUsagePage(el) == UInt32(kHIDPage_GenericDesktop) else { return }
    let usage = IOHIDElementGetUsage(el)
    guard usage == 0x30 || usage == 0x31 || usage == 0x38 else { return }
    let device = IOHIDElementGetDevice(el)
    let d = devs[device]
    print("val,\(micros(IOHIDValueGetTimeStamp(value))),\(d?.name ?? "?"),\(d?.transport ?? "?"),\(usage),\(IOHIDValueGetIntegerValue(value)),")
}, nil)

IOHIDManagerScheduleWithRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.defaultMode.rawValue)
// Devices are opened one by one in the matching callback, so one that is held
// exclusively by another program doesn't stop the rest from being read.

let mask: CGEventMask =
    (1 << CGEventType.mouseMoved.rawValue) | (1 << CGEventType.leftMouseDragged.rawValue) |
    (1 << CGEventType.rightMouseDragged.rawValue) | (1 << CGEventType.otherMouseDragged.rawValue)
if let tap = CGEvent.tapCreate(
    tap: .cgSessionEventTap, place: .headInsertEventTap, options: .listenOnly,
    eventsOfInterest: mask,
    callback: { _, _, event, _ in
        let p = event.location
        let dx = event.getDoubleValueField(.mouseEventDeltaX)
        let dy = event.getDoubleValueField(.mouseEventDeltaY)
        // CGEvent timestamps are already nanoseconds on the same clock.
        print(String(format: "cg,%llu,,,%.3f,%.3f,%.2f %.2f", event.timestamp / 1000, dx, dy, p.x, p.y))
        return Unmanaged.passUnretained(event)
    }, userInfo: nil)
{
    let src = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetMain(), src, .commonModes)
    CGEvent.tapEnable(tap: tap, enable: true)
} else {
    err("event tap unavailable: no cg rows")
}

let seconds = CommandLine.arguments.count > 1 ? Double(CommandLine.arguments[1]) ?? 30 : 30
signal(SIGINT) { _ in fflush(stdout); exit(0) }
DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { fflush(stdout); exit(0) }
err("recording \(Int(seconds)) s")
CFRunLoopRun()
