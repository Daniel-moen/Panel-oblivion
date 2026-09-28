/* The property the person last opened, so the list they come back to can
   mark its card. Session memory only; nothing else reads or writes it. */
export const recent = $state({ key: null });
