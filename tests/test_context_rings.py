import asyncio
import os
import uuid
import sys
from tripartite_memory.core import MemoryCore

async def test_split_brain_isolation():
    print("🚀 INITIALIZING CONTEXT RING ISOLATION TEST...")
    memory = MemoryCore()
    
    test_id = str(uuid.uuid4())[:8]
    family_secret = f"Family Secret {test_id}: Penny wants a telescope for her birthday."
    
    try:
        # 1. Ingest as Ring 1 (Personal/Family)
        print(f"📥 Ingesting Personal Memory (Ring 1): '{family_secret}'")
        await memory.ingest(
            content=family_secret,
            actor="john_alva",
            ring_level=1,
            collection="family_finances"
        )
        
        # Give Qdrant a second
        await asyncio.sleep(1)
        
        # 2. Recall as Ring 2 (Business) - SHOULD BE BLIND
        print("🔍 Attempting recall with Business Authorization (Ring 2)...")
        context_ring2 = await memory.recall(
            intent=f"telescope {test_id}", 
            collection="family_finances",
            authorized_ring=2
        )
        
        found_in_ring2 = any(test_id in h.payload.get("text", "") for h in context_ring2.historical_precedents)
        if not found_in_ring2:
            print("✅ SUCCESS: Business Agent (Ring 2) is blind to Family Secret (Ring 1).")
        else:
            print("❌ FAILURE: Business Agent leaked Family data!")

        # 3. Recall as Ring 1 (Personal) - SHOULD SEE IT
        print("🔍 Attempting recall with Personal Authorization (Ring 1)...")
        context_ring1 = await memory.recall(
            intent=f"telescope {test_id}", 
            collection="family_finances",
            authorized_ring=1
        )
        
        found_in_ring1 = any(test_id in h.payload.get("text", "") for h in context_ring1.historical_precedents)
        if found_in_ring1:
            print("✅ SUCCESS: Personal Agent (Ring 1) correctly retrieved the secret.")
        else:
            print("❌ FAILURE: Personal Agent could not see its own ring data.")

    finally:
        await memory.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        import selectors
        loop_factory = lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.run(test_split_brain_isolation(), loop_factory=loop_factory)
    else:
        asyncio.run(test_split_brain_isolation())
