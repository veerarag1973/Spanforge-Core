"""Remove duplicate method definitions from identity.py."""
import re

path = "src/spanforge/sdk/identity.py"
content = open(path, encoding="utf-8").read()

# The duplicate starts at the SECOND occurrence of "# ID-031: MFA enforcement policy"
marker = "    # ------------------------------------------------------------------\n    # ID-031: MFA enforcement policy"
first = content.find(marker)
second = content.find(marker, first + 1)

if second == -1:
    print("No duplicate found — already clean.")
else:
    print(f"First at char {first}, second at char {second}")
    # The duplicate ends just before "    # Private helpers"
    private_helpers = "\n    # ------------------------------------------------------------------\n    # Private helpers\n    # ------------------------------------------------------------------\n"
    end_of_dup = content.find(private_helpers, second)
    print(f"End of duplicate at char {end_of_dup}")

    # Remove from second occurrence up to (but not including) private helpers
    new_content = content[:second] + content[end_of_dup:]
    open(path, "w", encoding="utf-8").write(new_content)
    print("Duplicate removed successfully.")
