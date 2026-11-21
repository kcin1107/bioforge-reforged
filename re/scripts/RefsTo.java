// Lists functions referencing each given data address (including word-operand matches).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.Reference;
public class RefsTo extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String a : getScriptArgs()) {
            var addr = toAddr(a);
            java.util.Set<String> fns = new java.util.TreeSet<>();
            for (Reference r : getReferencesTo(addr)) {
                Function f = getFunctionContaining(r.getFromAddress());
                fns.add((f == null ? "?" : f.getName()) + "@" + r.getFromAddress());
            }
            println(a + " <- " + fns);
        }
    }
}
