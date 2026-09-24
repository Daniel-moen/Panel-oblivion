/* The editor's working state: the recipe being edited, its undo history, and
   the save → render loop.

   Every change goes through set()/touch(). They schedule a save on a short
   debounce; when the save lands, `renderKey` changes and the preview asks the
   server for a fresh /developed. Saves never overlap: a change made while one
   is in flight is picked up by a second save straight after.

   While the crop tool is open the server is sent the recipe with the crop
   opened out to the full frame, so you draw the new crop on the whole
   picture; closing the tool saves the real one. */

import { pe, fullRecipe, cleanRecipe, hash } from '$lib/media/photoedit.js';
import { say } from '$lib/media.svelte.js';

const DEBOUNCE = 280;
const FULL = [0, 0, 1, 1];

export function createEditor() {
  const ed = $state({
    id: null,
    copy: null,
    recipe: fullRecipe({}),
    loaded: false,
    error: null,
    canEdit: true,
    cropping: false,
    saving: false,
    saveError: null,
    renderKey: '0',
    undo: [],
    redo: []
  });

  let timer = null;
  let inflight = false;
  let again = false;
  let lastSaved = null;
  let dirty = false;            // anything changed since the photo was opened

  const effective = () => {
    const r = cleanRecipe($state.snapshot(ed.recipe));
    if (ed.cropping) r.crop = [...FULL];
    return r;
  };

  async function flush() {
    clearTimeout(timer);
    timer = null;
    if (!ed.canEdit || ed.id == null || !dirty) return;
    if (inflight) { again = true; return; }
    const body = effective();
    const s = JSON.stringify(body);
    if (s === lastSaved) { ed.renderKey = hash(s); return; }
    inflight = true;
    ed.saving = true;
    const id = ed.id, copy = ed.copy;
    try {
      await pe.save(id, body, copy);
      if (id === ed.id && copy === ed.copy) {
        lastSaved = s;
        ed.saveError = null;
        ed.renderKey = hash(s);
      }
    } catch (e) {
      ed.saveError = e.message;
      say(e.message || 'Could not save the edit', 'error');
    } finally {
      inflight = false;
      ed.saving = false;
      if (again) { again = false; flush(); }
    }
  }

  function schedule() {
    dirty = true;
    clearTimeout(timer);
    timer = setTimeout(flush, DEBOUNCE);
  }

  /** Record the current recipe as an undo step. */
  function commit() {
    const s = JSON.stringify($state.snapshot(ed.recipe));
    if (ed.undo[ed.undo.length - 1] === s) return;
    ed.undo = [...ed.undo.slice(-79), s];
    ed.redo = [];
  }

  return {
    ed,

    async load(id, copy) {
      clearTimeout(timer);
      ed.id = id;
      ed.copy = copy || null;
      ed.loaded = false;
      ed.error = null;
      ed.cropping = false;
      dirty = false;
      try {
        const r = await pe.get(id, copy || null);
        if (ed.id !== id) return;
        ed.recipe = fullRecipe(r.recipe);
        const s = JSON.stringify(cleanRecipe($state.snapshot(ed.recipe)));
        // what the server holds may be {} (never edited); treat it as saved
        // only if the stored text says the same thing
        lastSaved = r.recipe && Object.keys(r.recipe).length ? s : null;
        ed.renderKey = hash(s);
        ed.undo = [JSON.stringify($state.snapshot(ed.recipe))];
        ed.redo = [];
        ed.loaded = true;
      } catch (e) {
        ed.error = e.message;
      }
    },

    /** Change one field; `done` records an undo step (a slider's release). */
    set(k, v, done = false) {
      ed.recipe[k] = v;
      schedule();
      if (done) commit();
    },

    /** After mutating ed.recipe in place (masks, removes…). */
    touch(done = true) {
      schedule();
      if (done) commit();
    },

    /** Replace the whole recipe (Auto, a preset, a snapshot). */
    replace(r) {
      ed.recipe = fullRecipe(r);
      schedule();
      commit();
    },

    commit,
    flush,

    undo() {
      if (ed.undo.length < 2) return;
      const cur = ed.undo[ed.undo.length - 1];
      ed.redo = [...ed.redo, cur];
      ed.undo = ed.undo.slice(0, -1);
      ed.recipe = JSON.parse(ed.undo[ed.undo.length - 1]);
      schedule();
    },

    redoStep() {
      if (!ed.redo.length) return;
      const s = ed.redo[ed.redo.length - 1];
      ed.redo = ed.redo.slice(0, -1);
      ed.undo = [...ed.undo, s];
      ed.recipe = JSON.parse(s);
      schedule();
    },

    setCropping(on) {
      if (ed.cropping === on) return;
      ed.cropping = on;
      dirty = true;
      flush();
    },

    /** Save whatever is pending now (leaving the page, switching copy). */
    async settle() {
      if (ed.cropping) ed.cropping = false;
      if (dirty && (timer || lastSaved !== JSON.stringify(effective()))) await flush();
    }
  };
}
