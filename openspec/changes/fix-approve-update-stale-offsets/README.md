# fix-approve-update-stale-offsets

approve_proposal (update) and _mark_deprecated_in_md change a block's byte length in place but never shift the cached file_offset of later blocks in the same .md file, corrupting the file on the next write to one of them
