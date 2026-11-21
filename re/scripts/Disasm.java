// Prints the disassembly of the function at each given address (seg:off).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;

public class Disasm extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String a : getScriptArgs()) {
            Function f = getFunctionAt(toAddr(a));
            println("== " + a + " " + (f == null ? "?" : f.getName()));
            if (f == null) continue;
            for (Instruction i : currentProgram.getListing().getInstructions(f.getBody(), true))
                println("  " + i.getAddress() + "  " + i);
        }
    }
}
