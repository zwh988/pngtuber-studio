<!--
  The keyboard shortcuts map in a modal dialog (M7 S5): opened with "?" in the editor,
  closed with Escape, the close button or a click outside.
-->
<script lang="ts">
  import { X } from "@lucide/svelte";
  import ShortcutsList from "./ShortcutsList.svelte";
  import IconButton from "./ui/IconButton.svelte";

  type Props = { open: boolean };

  let { open = $bindable(false) }: Props = $props();

  let dialog = $state<HTMLDialogElement | null>(null);

  $effect(() => {
    if (dialog === null) {
      return;
    }
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  });

  function onClick(e: MouseEvent): void {
    if (e.target === dialog) {
      open = false; // a click on the backdrop
    }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions (Escape closes a modal dialog natively; the click is only the backdrop) -->
<dialog bind:this={dialog} aria-labelledby="shortcuts-title" onclose={() => (open = false)} onclick={onClick}>
  <div class="inner">
    <div class="head">
      <h2 id="shortcuts-title">Keyboard shortcuts</h2>
      <IconButton icon={X} label="Close (Esc)" onclick={() => (open = false)} />
    </div>
    <ShortcutsList />
  </div>
</dialog>

<style>
  dialog {
    width: min(760px, calc(100vw - 48px));
    max-height: calc(100vh - 48px);
    padding: 0;
    border: 1px solid var(--border-strong);
    border-radius: var(--r-lg);
    background: var(--surface-1);
    color: var(--text-1);
  }
  dialog::backdrop {
    background: rgba(0, 0, 0, 0.55);
  }
  .inner {
    padding: 14px 18px 18px;
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }
  h2 {
    margin: 0;
    font-size: var(--fs-lg);
    font-weight: 600;
  }
</style>
