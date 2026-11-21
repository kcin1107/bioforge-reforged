// Recovers far data pointers built as "PUSH DS / PUSH imm16" (MetaWare large model).
// Adds a data reference from the PUSH imm to DGROUP:imm, and defines a C string
// there if the bytes form a printable NUL-terminated string.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.data.TerminatedStringDataType;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.*;

public class RecoverFarDataRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        MemoryBlock dgroup = null;
        for (MemoryBlock b : currentProgram.getMemory().getBlocks())
            if (b.getStart().toString().startsWith("1290:")) dgroup = b;
        if (dgroup == null) throw new Exception("DGROUP 1290 not found");
        Address base = dgroup.getStart();
        long size = dgroup.getSize();
        Listing listing = currentProgram.getListing();
        ReferenceManager rm = currentProgram.getReferenceManager();
        int refs = 0, strs = 0;
        for (Instruction i : listing.getInstructions(true)) {
            if (monitor.isCancelled()) break;
            if (!i.getMnemonicString().equals("PUSH")) continue;
            Scalar s = i.getScalar(0);
            Instruction p = i.getPrevious();
            if (s == null || p == null || !p.toString().equals("PUSH DS")) continue;
            long off = s.getUnsignedValue();
            if (off >= size) continue;
            Address tgt = base.add(off);
            rm.addMemoryReference(i.getAddress(), tgt, RefType.DATA, SourceType.ANALYSIS, 0);
            refs++;
            if (listing.getDefinedDataAt(tgt) == null && looksLikeString(tgt)) {
                try {
                    listing.clearCodeUnits(tgt, tgt, false);
                    listing.createData(tgt, TerminatedStringDataType.dataType);
                    strs++;
                } catch (Exception e) { /* overlaps existing data */ }
            }
        }
        println("FAR_REFS " + refs + " NEW_STRINGS " + strs);
    }

    private boolean looksLikeString(Address a) {
        try {
            int n = 0;
            while (n < 512) {
                int c = getByte(a.add(n)) & 0xff;
                if (c == 0) return n >= 2;
                if (c < 0x20 && c != '\n' && c != '\r' && c != '\t') return false;
                if (c > 0x7e) return false;
                n++;
            }
        } catch (Exception e) { }
        return false;
    }
}
