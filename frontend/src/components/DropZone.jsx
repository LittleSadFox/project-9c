import { useRef, useState } from "react";

import { t } from "../i18n/index.js";
import { Button } from "./glass.jsx";

function collectFiles(dataTransfer) {
  if (!dataTransfer) {
    return [];
  }
  if (dataTransfer.files && dataTransfer.files.length) {
    return [...dataTransfer.files];
  }
  return [];
}

export function DropZone({ onFiles, children, disabled = false }) {
  const inputRef = useRef(null);
  const [active, setActive] = useState(false);

  function emit(files) {
    if (disabled || !files.length) {
      return;
    }
    onFiles(files);
  }

  return (
    <div
      className={`drop-zone${active ? " drop-zone-active" : ""}`}
      onDragEnter={(event) => {
        event.preventDefault();
        if (!disabled) {
          setActive(true);
        }
      }}
      onDragOver={(event) => {
        event.preventDefault();
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setActive(false);
        }
      }}
      onDrop={(event) => {
        event.preventDefault();
        setActive(false);
        emit(collectFiles(event.dataTransfer));
      }}
    >
      <div className="drop-zone-toolbar">
        <input
          ref={inputRef}
          className="sr-only"
          type="file"
          accept="video/*"
          multiple
          disabled={disabled}
          onChange={(event) => {
            emit([...event.target.files]);
            event.target.value = "";
          }}
        />
        <Button variant="primary" disabled={disabled} onClick={() => inputRef.current && inputRef.current.click()}>
          {t("action.import")}
        </Button>
        <span className="page-copy">{t("library.dropHint")}</span>
      </div>
      {children}
    </div>
  );
}
