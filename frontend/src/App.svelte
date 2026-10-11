<script lang="ts">
  type Hello = { app: string; status: string; schema_version: number };

  let hello = $state<Hello | null>(null);
  let error = $state<string | null>(null);

  async function load(): Promise<void> {
    try {
      const response = await fetch("/api/hello");
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      hello = (await response.json()) as Hello;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  void load();
</script>

<main>
  <h1>PNGtuber Studio</h1>
  {#if error !== null}
    <p class="error">Backend error: {error}</p>
  {:else if hello === null}
    <p>Connecting to backend...</p>
  {:else}
    <p>Backend: {hello.status} (schema v{hello.schema_version})</p>
  {/if}
</main>

<style>
  main {
    font-family: system-ui, sans-serif;
    padding: 2rem;
  }
  .error {
    color: #b00020;
  }
</style>
