# fix-installer-seed-overwrites-existing-kb

seed_knowledge_base() in install.sh does a blind cp of the repo's bundled example .md files over any existing file of the same name in KNOWLEDGE_BASE_PATH, silently destroying real data with no backup
