import { useCallback, useState } from "react";

export function useUndo() {
  const [state, setState] = useState({ stack: [], index: -1 });

  const run = useCallback(async (command) => {
    await command.do();
    setState((current) => {
      const stack = current.stack.slice(0, current.index + 1);
      stack.push(command);
      return { stack, index: stack.length - 1 };
    });
  }, []);

  const undo = useCallback(async () => {
    let command = null;
    setState((current) => {
      if (current.index < 0) {
        return current;
      }
      command = current.stack[current.index];
      return { ...current, index: current.index - 1 };
    });
    if (command) {
      await command.undo();
    }
  }, []);

  const redo = useCallback(async () => {
    let command = null;
    setState((current) => {
      if (current.index >= current.stack.length - 1) {
        return current;
      }
      command = current.stack[current.index + 1];
      return { ...current, index: current.index + 1 };
    });
    if (command) {
      await command.do();
    }
  }, []);

  return {
    run,
    undo,
    redo,
    canUndo: state.index >= 0,
    canRedo: state.index < state.stack.length - 1,
  };
}
