// BioForge native port, stage 1: shows the cameras (ROOMS/*.CAM backgrounds) of the user's game folder.
import AppKit

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
