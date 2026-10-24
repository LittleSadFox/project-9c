import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProposalList } from "./ProposalList.jsx";
import { proposalFixture, proposalTwoFixture } from "../test/fixtures.js";

describe("ProposalList", () => {
  it("selects a proposal and toggles batch checks", () => {
    const onSelect = vi.fn();
    const onToggle = vi.fn();
    render(
      <ProposalList
        proposals={[proposalFixture, proposalTwoFixture]}
        selectedId="prop-1"
        checkedIds={["prop-1"]}
        onSelect={onSelect}
        onToggle={onToggle}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /60–90/ }));
    expect(onSelect).toHaveBeenCalledWith(proposalTwoFixture);
    fireEvent.click(screen.getByLabelText("Select prop-2"));
    expect(onToggle).toHaveBeenCalledWith("prop-2");
  });
});
