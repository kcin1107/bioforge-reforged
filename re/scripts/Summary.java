// Prints a load summary: language, memory blocks, function count, imports.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.*;

public class Summary extends GhidraScript {
    @Override
    public void run() throws Exception {
        println("LANG " + currentProgram.getLanguageID() + " / " + currentProgram.getExecutableFormat());
        int code = 0;
        for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
            if (b.isExecute()) code++;
        }
        println("BLOCKS " + currentProgram.getMemory().getBlocks().length + " (exec " + code + ")");
        println("FUNCTIONS " + currentProgram.getFunctionManager().getFunctionCount());
        SymbolTable st = currentProgram.getSymbolTable();
        int ext = 0;
        for (Symbol s : st.getExternalSymbols()) {
            if (ext++ < 400) println("EXT " + s.getParentNamespace().getName() + "::" + s.getName()
                + " refs=" + s.getReferenceCount());
        }
        println("EXTERNALS " + ext);
    }
}
