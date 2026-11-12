#!/bin/bash
# Rebuild builder/macos/Hookshot.app from the Swift sources beside this script.
set -eu
cd "$(dirname "$0")"
sdk="$(xcrun --sdk macosx --show-sdk-path)"
mkdir -p Hookshot.app/Contents/MacOS
out="$(mktemp "${TMPDIR:-/tmp}/hookshot-builder.XXXXXX")"
swiftc -parse-as-library -O -sdk "$sdk" -target arm64-apple-macosx14.0 \
    -o "$out" \
    Sources/HookshotApp.swift Sources/BuilderModel.swift
mv "$out" Hookshot.app/Contents/MacOS/hookshot-builder
chmod 755 Hookshot.app/Contents/MacOS/hookshot-builder
codesign -s - --force Hookshot.app
