// Finds instructions with a scalar operand equal to any given hex value; prints function and context.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
public class FindScalar extends GhidraScript {
    @Override
    public void run() throws Exception {
        java.util.Set<Long> want = new java.util.HashSet<>();
        for (String a : getScriptArgs()) want.add(Long.parseLong(a, 16));
        for (Instruction i : currentProgram.getListing().getInstructions(true))
            for (int k = 0; k < i.getNumOperands(); k++) {
                var s = i.getScalar(k);
                if (s != null && want.contains(s.getUnsignedValue())) {
                    Function f = getFunctionContaining(i.getAddress());
                    println(String.format("%x %s %s  %s", s.getUnsignedValue(), i.getAddress(), f == null ? "?" : f.getName(), i));
                }
            }
    }
}
