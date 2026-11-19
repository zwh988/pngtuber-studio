<!--
  Keyboard shortcuts map (M7 S5, decision 3: read only). Used on the Settings page
  and in the editor's "?" dialog. The table lives in hotkeys.ts.
-->
<script lang="ts">
  import { HOTKEY_GROUPS, HOTKEY_NOTE } from "./hotkeys";
</script>

<div class="groups">
  {#each HOTKEY_GROUPS as group (group.title)}
    <section>
      <h3>{group.title}</h3>
      <dl>
        {#each group.items as item (item.action)}
          <dt>
            {#each [item.keys, ...(item.alts ?? [])] as combo, i (i)}
              {#if i > 0}<span class="or">or</span>{/if}
              {#each combo as key, k (k)}
                {#if k > 0}<span class="plus">+</span>{/if}<kbd class="kbd">{key}</kbd>
              {/each}
            {/each}
          </dt>
          <dd>{item.action}</dd>
        {/each}
      </dl>
    </section>
  {/each}
</div>
<p class="note">{HOTKEY_NOTE}</p>

<style>
  .groups {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 16px 24px;
  }
  h3 {
    margin: 0 0 6px;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-2);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  dl {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    gap: 6px 12px;
    margin: 0;
    align-items: baseline;
  }
  dt {
    display: flex;
    align-items: center;
    gap: 3px;
    white-space: nowrap;
  }
  dd {
    margin: 0;
    color: var(--text-1);
  }
  .or,
  .plus {
    color: var(--text-3);
    font-size: var(--fs-xs);
    padding: 0 2px;
  }
  .note {
    margin: 12px 0 0;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
</style>
