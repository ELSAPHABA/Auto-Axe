import { create } from "zustand";

export type RatioKind =
  "global_accounts" | "top_accounts" | "top_positions" | "taker_volume";

type UiState = {
  showRatios: boolean;
  ratioKind: RatioKind;
  toggleRatios: () => void;
  setRatioKind: (kind: RatioKind) => void;
};

export const useUi = create<UiState>((set) => ({
  showRatios: false,
  ratioKind: "global_accounts",
  toggleRatios: () => set((old) => ({ showRatios: !old.showRatios })),
  setRatioKind: (kind) => set({ ratioKind: kind }),
}));
