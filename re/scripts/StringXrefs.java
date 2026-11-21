// Dumps every defined string with the functions that reference it (TSV to arg[0]).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.Reference;
import java.io.PrintWriter;
import java.util.*;

public class StringXrefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        PrintWriter out = new PrintWriter(getScriptArgs()[0]);
        int n = 0;
        for (Data d : currentProgram.getListing().getDefinedData(true)) {
            if (!d.hasStringValue()) continue;
            Set<String> fns = new TreeSet<>();
            for (Reference r : getReferencesTo(d.getAddress())) {
                Function f = getFunctionContaining(r.getFromAddress());
                fns.add(f == null ? r.getFromAddress().toString() : f.getName() + "@" + f.getEntryPoint());
            }
            String s = String.valueOf(d.getValue()).replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r");
            out.println(d.getAddress() + "\t" + s + "\t" + String.join(",", fns));
            n++;
        }
        out.close();
        println("STRINGS " + n);
    }
}
