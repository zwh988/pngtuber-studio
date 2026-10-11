export {};

declare global {
  interface Window {
    pywebview?: {
      api?: {
        pick_folder?: () => Promise<string | null>;
        pick_file?: () => Promise<string | null>;
      };
    };
  }
}
