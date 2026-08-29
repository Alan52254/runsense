import { StyleSheet, TextInput } from 'react-native';

// Minimal date entry: a plain YYYY-MM-DD text field. A calendar-picker
// component is a reasonable future polish item but isn't required for
// the spec -- it only requires that an explicit date can be chosen and
// sent through unchanged, not any particular picker widget.
export default function DateField({
  value,
  onChangeText,
  placeholder = 'YYYY-MM-DD',
}: {
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
}) {
  return (
    <TextInput
      style={styles.input}
      value={value}
      onChangeText={onChangeText}
      placeholder={placeholder}
      autoCapitalize="none"
      keyboardType="numbers-and-punctuation"
      maxLength={10}
    />
  );
}

const styles = StyleSheet.create({
  input: {
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 8,
    padding: 10,
    fontSize: 14,
    minWidth: 120,
  },
});
