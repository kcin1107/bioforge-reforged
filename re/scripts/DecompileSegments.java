// Decompiles every function in the given segments to <outdir>/<seg>.c
// args: outdir seg [seg ...]   e.g.  re/decomp 1038 1080
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import java.io.*;

public class DecompileSegments extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        File dir = new File(a[0]); dir.mkdirs();
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        for (int k = 1; k < a.length; k++) {
            String seg = a[k].toLowerCase();
            try (PrintWriter out = new PrintWriter(new File(dir, seg + ".c"))) {
                int n = 0;
                for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                    if (!f.getEntryPoint().toString().startsWith(seg + ":")) continue;
                    DecompileResults r = di.decompileFunction(f, 60, monitor);
                    out.println("// ---- " + f.getName() + " @ " + f.getEntryPoint());
                    out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// decompile failed: " + r.getErrorMessage());
                    n++;
                }
                println("SEG " + seg + " functions " + n);
            }
        }
        di.dispose();
    }
}
