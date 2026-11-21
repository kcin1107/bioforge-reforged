// Disassembles and creates a function at each given address (seg:off) if Ghidra has none, then prints its decompilation.
// Changes are not saved (run with -readOnly).  args: seg:off [seg:off ...]
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class DecompileAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        for (String a : getScriptArgs()) {
            Address at = toAddr(a);
            Function f = getFunctionAt(at);
            if (f == null) {
                new DisassembleCommand(at, null, true).applyTo(currentProgram, monitor);
                f = createFunction(at, null);
            }
            println("== " + a + " " + (f == null ? "? (no function)" : f.getName()));
            if (f == null) continue;
            DecompileResults r = d.decompileFunction(f, 60, monitor);
            println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "decompile failed: " + r.getErrorMessage());
        }
    }
}
